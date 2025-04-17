import asyncio
import websockets
import json
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.clock import Clock
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from threading import Thread

MARKETS = ['1HZ25V', '1HZ10V', '1HZ75V', 'HZ100V', '1HZ50V', 'R_25', 'R_10', 'R_75', 'R_50', 'R_100']
DURATION = 1  # in ticks

class DerivBot(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', **kwargs)
        self.running = False
        self.digit_history = []
        self.current_stake = 0.35
        self.wins = 0
        self.losses = 0

        self.api_input = TextInput(text="UFuZxvFb8SwWBYt", multiline=False, hint_text="API Token")
        self.market_spinner = Spinner(text=MARKETS[0], values=MARKETS, size_hint_y=None, height=40)
        self.stake_input = TextInput(text="0.35", multiline=False, hint_text="Stake")
        self.over_barrier_input = TextInput(text="7", multiline=False, hint_text="Digit Over Barrier")
        self.under_barrier_input = TextInput(text="3", multiline=False, hint_text="Digit Under Barrier")

        self.info_label = Label(text="Waiting to start...", size_hint_y=None, height=40)
        self.digits_label = Label(text="Last Digits: []", size_hint_y=None, height=60)
        self.balance_label = Label(text="Balance: ?", size_hint_y=None, height=60)
        self.stats_label = Label(text="Wins: 0 | Losses: 0", size_hint_y=None, height=40)

        self.start_btn = Button(text="Start Bot", background_color=(0, 1, 0, 1), size_hint_y=None, height=100)
        self.stop_btn = Button(text="Stop Bot", background_color=(1, 0, 0, 1), size_hint_y=None, height=100)

        self.start_btn.bind(on_press=self.start_bot)
        self.stop_btn.bind(on_press=self.stop_bot)

        self.add_widget(self.api_input)
        self.add_widget(self.market_spinner)
        self.add_widget(self.stake_input)
        self.add_widget(self.over_barrier_input)
        self.add_widget(self.under_barrier_input)
        self.add_widget(self.balance_label)
        self.add_widget(self.digits_label)
        self.add_widget(self.stats_label)
        self.add_widget(self.info_label)
        self.add_widget(self.start_btn)
        self.add_widget(self.stop_btn)

    def start_bot(self, instance):
        self.running = True
        self.info_label.text = "Bot running..."
        self.current_stake = float(self.stake_input.text)
        self.wins = 0
        self.losses = 0
        self.digit_history.clear()
        self.update_stats()
        Thread(target=self.run_bot).start()

    def stop_bot(self, instance):
        self.running = False
        self.info_label.text = "Bot stopped."

    def update_digits(self, digit):
        self.digit_history.append(digit)
        if len(self.digit_history) > 3:
            self.digit_history.pop(0)
        self.digits_label.text = f"Last Digits: {self.digit_history}"

    def update_stats(self):
        self.stats_label.text = f"Wins: {self.wins} | Losses: {self.losses}"

    def run_bot(self):
        asyncio.run(self.deriv_stream())

    async def deriv_stream(self):
        url = f"wss://ws.derivws.com/websockets/v3?app_id=70489"
        async with websockets.connect(url) as ws:
            api_token = self.api_input.text.strip()
            await ws.send(json.dumps({"authorize": api_token}))
            await ws.recv()

            await ws.send(json.dumps({"balance": 1, "subscribe": 1}))
            await ws.send(json.dumps({
                "ticks": self.market_spinner.text,
                "subscribe": 1
            }))

            while self.running:
                try:
                    data = await ws.recv()
                    msg = json.loads(data)

                    if 'tick' in msg:
                        digit = int(str(msg['tick']['quote'])[-1])
                        Clock.schedule_once(lambda dt: self.update_digits(digit))
                        if len(self.digit_history) == 3:
                            await self.check_and_trade(ws)

                    elif 'balance' in msg:
                        balance = msg['balance']['balance']
                        Clock.schedule_once(lambda dt: self.update_balance(balance))

                except Exception as e:
                    Clock.schedule_once(lambda dt: self.info_label_update(f"Error: {e}"))
                    break

    async def check_and_trade(self, ws):
        digits = self.digit_history
        over_barrier = int(self.over_barrier_input.text)
        under_barrier = int(self.under_barrier_input.text)

        if all(d < 3 for d in digits):
            await self.place_trade(ws, "DIGITOVER", over_barrier, self.current_stake)
        elif all(d > 6 for d in digits):
            await self.place_trade(ws, "DIGITUNDER", under_barrier, self.current_stake)

    async def place_trade(self, ws, contract_type, barrier, stake):
        proposal = {
            "buy": 1,
            "price": stake,
            "parameters": {
                "amount": stake,
                "basis": "stake",
                "contract_type": contract_type,
                "currency": "USD",
                "duration": DURATION,
                "duration_unit": "t",
                "symbol": self.market_spinner.text,
                "barrier": str(barrier)
            }
        }
        await ws.send(json.dumps(proposal))
        response = await ws.recv()
        res_data = json.loads(response)

        if 'buy' in res_data:
            Clock.schedule_once(lambda dt: self.info_label_update(f"Trade placed: {contract_type} {barrier}"))

            while True:
                result_data = await ws.recv()
                result_msg = json.loads(result_data)

                if 'proposal_open_contract' in result_msg:
                    contract = result_msg['proposal_open_contract']
                    if contract.get("is_expired"):
                        profit = contract.get("profit", 0)

                        def update_result(dt):
                            if profit > 0:
                                self.wins += 1
                                self.info_label_update("WIN")
                            else:
                                self.losses += 1
                                self.info_label_update("LOSS")
                            self.update_stats()

                        Clock.schedule_once(update_result)
                        break
        else:
            Clock.schedule_once(lambda dt: self.info_label_update("Trade failed"))

    def update_balance(self, balance):
        self.balance_label.text = f"Balance: ${balance:.2f}"

    def info_label_update(self, text):
        self.info_label.text = text

class DerivApp(App):
    def build(self):
        return DerivBot()

if __name__ == '__main__':
    DerivApp().run()