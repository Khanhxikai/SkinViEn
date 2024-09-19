from flask import g, Flask, redirect, url_for, session, render_template, flash, request
from flask_openid import OpenID
import requests
import sqlite3
import json

app = Flask(__name__)
app.secret_key = 'your_secret_key'
oid = OpenID(app, safe_roots=[])

DATABASE = 'db/UserCredential.db'

STEAM_API_KEY = '680B686D92D0D3EC7C78F92BEA95D92D'
INVENTORY_API_URL = 'https://www.steamwebapi.com/steam/api/inventory'
STATIC_API_KEY = 'O0582864N057UWYX'
STEAM_OPENID_URL = 'https://steamcommunity.com/openid'

@app.route('/')
def index():
    return render_template('index.html')

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.route('/login')
@oid.loginhandler
def login():
    if 'steamid' in session:
        return redirect(url_for('profile'))
    return oid.try_login(STEAM_OPENID_URL)

def check_and_insert_steamid(steam_id):
    db = get_db()
    cursor = db.cursor()

    # Check if the SteamID already exists in the database
    cursor.execute("SELECT SteamID64 FROM CredentialData WHERE SteamID64 = ?", (steam_id,))
    result = cursor.fetchone()

    if result is None:
        # If SteamID does not exist, insert it with balance 0
        cursor.execute("INSERT INTO CredentialData (SteamID64, Balance) VALUES (?, 0)", (steam_id,))
        db.commit()

    cursor.close()

def check_trade_url(steam_id):
    db = get_db()
    cursor = db.cursor()

    # Check if the TradeURL for the given SteamID64 is empty
    cursor.execute("SELECT TradeURL FROM CredentialData WHERE SteamID64 = ?", (steam_id,))
    result = cursor.fetchone()

    cursor.close()

    if result is None or not result[0]:
        return "Please fill out your Trade Link"
    return None


@app.route('/update_trade_url', methods=['GET', 'POST'])
def update_trade_url():
    if 'steamid' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        trade_url = request.form['trade_url']
        steam_id = session['steamid']

        db = get_db()
        cursor = db.cursor()
        cursor.execute("UPDATE CredentialData SET TradeURL = ? WHERE SteamID64 = ?", (trade_url, steam_id))
        db.commit()
        cursor.close()

        flash('Trade Link updated successfully!')
        return redirect(url_for('profile'))

    return render_template('url.html')


@oid.after_login
def after_login(resp):
    steam_id = resp.identity_url.split('/')[-1]
    session['steamid'] = steam_id

    user_info = get_steam_user_info(steam_id)
    session['user_info'] = user_info

    # Check and insert the SteamID into the database if it's the user's first login
    check_and_insert_steamid(steam_id)

    return redirect(url_for('profile'))


def get_steam_user_info(steam_id):
    url = f'http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={STEAM_API_KEY}&steamids={steam_id}'
    response = requests.get(url)
    data = response.json()
    return data['response']['players'][0] if 'players' in data['response'] else None

def get_inventory(steam_id):
    url = f'{INVENTORY_API_URL}?key={STATIC_API_KEY}&steam_id={steam_id}'
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return None

def get_store_inventory():
    steam_id = '76561198844773157'
    url = f'{INVENTORY_API_URL}?key={STATIC_API_KEY}&steam_id={steam_id}'
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return None

def get_user_balance(steam_id):
    db = get_db()
    cursor = db.cursor()

    # Retrieve the balance for the current user
    cursor.execute("SELECT Balance FROM CredentialData WHERE SteamID64 = ?", (steam_id,))
    result = cursor.fetchone()

    balance = result[0] if result else 0  # Set balance to 0 if no record is found
    cursor.close()

    return balance

@app.route('/profile')
def profile():
    if 'steamid' not in session:
        return redirect(url_for('login'))

    steam_id = session['steamid']

    # Run the trade URL check
    trade_url_check = check_trade_url(steam_id)
    if trade_url_check:
        flash(trade_url_check)

    user_info = session.get('user_info')
    user_inventory = get_inventory(steam_id)
    store_inventory = get_store_inventory()
    user_balance = get_user_balance(steam_id)

    # Pretty-print inventories for debugging
    formatted_user_inventory = json.dumps(user_inventory, indent=4)
    formatted_store_inventory = json.dumps(store_inventory, indent=4)
    # print("Fetched User Inventory:", formatted_user_inventory)
    # print("Fetched Store Inventory:", formatted_store_inventory)

    return render_template('profile.html', user_info=user_info, user_inventory=user_inventory, store_inventory=store_inventory, user_balance=user_balance)


@app.route('/inventory')
def inventory():
    if 'steamid' not in session:
        return redirect(url_for('login'))

    inventory = get_inventory(session['steamid'])

    # Pretty-print inventory data for debugging
    formatted_inventory = json.dumps(inventory, indent=4)
    # print("Fetched Inventory:", formatted_inventory)

    return render_template('inventory.html', inventory=inventory)

@app.route('/balance')
def balance():
    if 'steamid' not in session:
        return redirect(url_for('login'))
    return render_template('balance.html')

@app.route('/process_topup', methods=['POST'])
def process_topup():
    if 'steamid' not in session:
        return redirect(url_for('login'))

    # Get the top-up amount from the form
    topup_amount = int(request.form['amount'])
    steam_id = session['steamid']

    # Update the user's balance in the database
    db = get_db()
    cursor = db.cursor()

    # Get current balance
    cursor.execute("SELECT Balance FROM CredentialData WHERE SteamID64 = ?", (steam_id,))
    current_balance = cursor.fetchone()[0]

    # Update balance
    new_balance = current_balance + topup_amount
    cursor.execute("UPDATE CredentialData SET Balance = ? WHERE SteamID64 = ?", (new_balance, steam_id))
    db.commit()

    cursor.close()

    flash(f'Balance topped up successfully! Your new balance is {new_balance}.')
    return redirect(url_for('profile'))


@app.route('/buy_item', methods=['POST'])
def buy_item():
    if 'steamid' not in session:
        return redirect(url_for('login'))

    # Retrieve the item ID and price from the form
    item_id = request.form.get('item_id')
    item_price = float(request.form.get('item_price'))  # Ensure this is passed from the form

    # Get the user's current balance from the database
    steamid = session['steamid']
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT Balance FROM CredentialData WHERE SteamID64 = ?", (steamid,))
    result = cursor.fetchone()

    if result is None:
        flash("User balance not found.")
        return redirect(url_for('profile'))

    user_balance = result[0]

    # Compare user balance with item price
    if user_balance < item_price:
        flash("Insufficient balance to purchase this item.")
        return redirect(url_for('profile'))

    # Deduct the item price from the user's balance
    new_balance = user_balance - item_price
    cursor.execute("UPDATE CredentialData SET Balance = ? WHERE SteamID64 = ?", (new_balance, steamid))
    db.commit()

    # Flash success message and redirect
    flash(f"Item {item_id} purchased successfully! Remaining balance: {new_balance} credits.")
    cursor.close()

    return redirect(url_for('profile'))


@app.route('/sell_item', methods=['POST'])
def sell_item():
    if 'steamid' not in session:
        return redirect(url_for('login'))

    # Retrieve the item details from the form
    item_price = float(request.form.get('item_price'))
    markethashname = request.form.get('markethashname')

    # Get the user's current balance from the database
    steamid = session['steamid']
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT Balance FROM CredentialData WHERE SteamID64 = ?", (steamid,))
    result = cursor.fetchone()

    if result is None:
        flash("User balance not found.")
        return redirect(url_for('profile'))

    user_balance = result[0]

    # Add the item price to the user's balance
    new_balance = user_balance + item_price
    cursor.execute("UPDATE CredentialData SET Balance = ? WHERE SteamID64 = ?", (new_balance, steamid))
    db.commit()

    # Flash success message with markethashname
    flash(f"Item '{markethashname}' sold successfully! New balance: {new_balance} credits.")
    cursor.close()

    return redirect(url_for('profile'))


@app.route('/logout')
def logout():
    session.pop('steamid', None)
    session.pop('user_info', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
