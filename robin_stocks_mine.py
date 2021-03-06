#!/usr/bin/python3
import time
import robin_stocks
import configparser
import json
import requests
import os
from barchart import Barchart
from new_finviz import FinViz
from work_sql import Track_Buys
from figure_std import Find_SLP
from yahoo_analysts import Yahoo_Analysts

barchart = Barchart()

config = configparser.ConfigParser()

fv_symbols = FinViz().full

def is_market_open():
    end = 'https://financialmodelingprep.com/api/v3/is-the-market-open?apikey=07d01d0e9e3d5d7aef46d93a6a0c4529'
    data = requests.get(end)
    data = json.loads(data.text)
    return data['isTheStockMarketOpen']

def prompt_creds():
  if os.path.isfile('/home/ec2-user/.saver.cfg'):
    os.remove('/home/ec2-user/.saver.cfg')
  username = input ("Enter RobinHood username: ")
  password = input ("Enter RobinHood password: ")
  config.add_section('ROBINHOOD')
  config['ROBINHOOD']['username'] = username
  config['ROBINHOOD']['password'] = password
  with open('/home/ec2-user/.saver.cfg', 'w') as configfile:
    config.write(configfile)

def get_creds():
  if os.path.isfile('/home/ec2-user/.saver.cfg') is False:
    prompt_creds()
  data = config.read('/home/ec2-user/.saver.cfg')
  if config.has_section('ROBINHOOD') is False:
    prompt_creds()
  if config.has_option('ROBINHOOD', 'username') is False:
    prompt_creds()
  if config.has_option('ROBINHOOD', 'password') is False:
    prompt_creds()
  username = config['ROBINHOOD']['username']
  password = config['ROBINHOOD']['password']
  return username, password

def get_rh_rating(symbol, analyst):
    data = robin_stocks.stocks.get_ratings(symbol, info=None)
    if isinstance(data, str) is True:
        data = data.rstrip('\n')
        if len(data) == 0:
            return None
    if data is None:
        return None
    if data['summary'] is None:
        return None
    buy = data['summary']['num_buy_ratings']
    if buy < analyst:
        return None
    hold = data['summary']['num_hold_ratings']
    sell = data['summary']['num_sell_ratings']
    total = buy + hold + sell
    per = buy / total * 100
    if per > 90:
        return True

def get_cp(symbol):
    data = robin_stocks.stocks.get_quotes(symbol)[0]
    if data is None:
        return False
    else:
        cp = float(data['last_trade_price'])
        return cp
    
def buy(symbol):
    if is_market_open() is False:
        return False
    cp = get_cp(symbol)
    if cp is False:
        return False
    limitprice = cp * 1.0025
    quantity = int(100 / cp)
    if quantity == 0:
        quantity = 1
    cash = float(robin_stocks.profiles.load_account_profile(info=None)['cash'])
    if cash < limitprice:
        print("Unable to buy %s not enough cash" % symbol)
        return False
    if cash < limitprice * quantity:
        quantity = 1
    buy_data = robin_stocks.orders.order_buy_limit(symbol, quantity,limitprice,timeInForce='gtc', extendedHours=False)
    order = buy_data['id']
    while buy_data['state'] == 'queued':
        time.sleep(10)
        buy_data = robin_stocks.orders.get_stock_order_info(order)
    if buy_data['state'] == 'filled':
        return True
    print("Failed to buy %s last state was %s" % ( symbol, buy_data['state']))
    return False

def get_positions():
    open_positions = robin_stocks.account.build_holdings(with_dividends=False)
    held_symbols = {}
    for k in open_positions:
        quantity = int(open_positions[k]['quantity'].split('.')[0])
        held_symbols[k] = quantity
    return held_symbols

def get_slp(symbol):
   if symbol == 'BRK.B':
       slp_per = Find_SLP().get_slp('BRK-B')
   else:
      slp_per = Find_SLP().get_slp(symbol)
   cp = get_cp(symbol)
   if cp is False:
       return False
   slp = cp * slp_per
   slp = float("%.2f" % round(slp, 2))
   return int(slp)

def set_slp(symbol, quantity):
    orders = robin_stocks.orders.find_stock_orders(symbol=symbol)
    slp = get_slp(symbol)
    for order in orders:
        state = order['state']
        side = order['side']
        if state == 'confirmed' and side == 'sell':
            current_slp = float(order['stop_price'])
            current_slp = int(float("%.2f" % round(current_slp, 2)))
            if slp <= current_slp:
                print("%s has a SLP set of %i , the new SLP would be lower at %i, so I am not updating it" % ( symbol, current_slp, slp))
            else:
                print("%s has a SLP set of %i , the new SLP would be HIGHER at %i, so I am updating it" % ( symbol, current_slp, slp))
                print("Cancelling order")
                robin_stocks.orders.cancel_stock_order(order['id'])
                time.sleep(10)
                robin_stocks.orders.order_sell_stop_loss(symbol, quantity, slp, timeInForce='gtc', extendedHours=False)
                return True
    return False

username, password = get_creds()
robin_stocks.login(username, password)
open_positions = get_positions()
bought_symbols = Track_Buys().get_symbols()
symbols = FinViz().full()
buys = []

for symbol in sorted(set(symbols)):
    if get_rh_rating(symbol, 10) is True and Yahoo_Analysts().is_buy(symbol) is True:
        print("%s is a buy" % symbol)
        buys.append(symbol)
        cp = get_cp(symbol)
        if cp is False:
            continue
        Track_Buys().buy(symbol, cp, True)
        if symbol not in bought_symbols:
            print("%s is a new buy,buying" % symbol)
            Track_Buys().buy(symbol, get_cp(symbol), True)
            #buy(symbol)

for symbol in bought_symbols:
    cp = get_cp(symbol)
    if cp is False:
        continue
    if symbol not in buys:
        Track_Buys().update_price(symbol, cp, False)

for symbol in buys:
    if symbol not in open_positions:
        print("Symbol %s is a buy, but not bought in RH buying it" % symbol)
        buy(symbol)

print(buys)
time.sleep(5)

for symbol, quantity in get_positions().items():
    cp = get_cp(symbol)
    if cp is False:
        continue
    slp = get_slp(symbol)
    time.sleep(10)
    print("The SLP for %s is %i the cp is %i" % ( symbol,slp,cp))
    set_slp(symbol,quantity)
