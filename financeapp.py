import streamlit as st
import pandas as pd
import yfinance as yf
import sqlite3
import requests
from datetime import datetime, timedelta
import plotly.express as px
import re
import calendar
import time
import hashlib
import secrets

# --- Constants & DB ---
DB_PATH = "finance_app.db"

# --- Initialize session state ---
if "messages" not in st.session_state:
    st.session_state.messages = []

if "modal_open" not in st.session_state:
    st.session_state.modal_open = False

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "user_id" not in st.session_state:
    st.session_state.user_id = None

# --- Safe rerun helper ---
def safe_rerun():
    try:
        st.rerun()
    except AttributeError:
        try:
            params = st.query_params
            params["_rerun_ts"] = str(datetime.utcnow().timestamp())
            st.query_params.update(params)
        except Exception:
            st.stop()

# --- DATABASE HELPERS ---
# (init_db, hash_password, register_user, login_user, set_config, get_config, add_holding, get_holdings, remove_holding, add_transaction, get_transactions, remove_transaction, save_user_profile, get_user_profile, add_savings_goal, update_savings_goal, get_savings_goals, remove_savings_goal remain unchanged)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # --- Migrate users table ---
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    users_table_exists = c.fetchone()

    if users_table_exists:
        c.execute("PRAGMA table_info(users)")
        columns = {col[1]: col[2] for col in c.fetchall()}
        required_columns = {
            'id': 'INTEGER',
            'username': 'TEXT',
            'password_hash': 'TEXT',
            'email': 'TEXT',
            'created_at': 'TEXT'
        }
        if 'id' not in columns or 'password_hash' not in columns:
            c.execute('''
                CREATE TABLE users_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT,
                    email TEXT UNIQUE,
                    created_at TEXT
                )
            ''')
            old_columns = list(columns.keys())
            common_columns = [col for col in old_columns if col in ['username', 'email', 'created_at']]
            has_password = 'password' in columns
            select_columns = common_columns[:]
            if has_password:
                select_columns.append('password')
            select_columns_str = ', '.join(select_columns)
            c.execute(f'SELECT {select_columns_str} FROM users')
            old_data = c.fetchall()
            for row in old_data:
                row_dict = dict(zip(select_columns, row))
                username = row_dict.get('username')
                email = row_dict.get('email', None)
                created_at = row_dict.get('created_at', datetime.utcnow().isoformat())
                password_hash = hash_password(row_dict['password']) if has_password and row_dict.get('password') else None
                c.execute('''
                    INSERT INTO users_new (username, password_hash, email, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (username, password_hash, email, created_at))
            c.execute('DROP TABLE users')
            c.execute('ALTER TABLE users_new RENAME TO users')
    else:
        c.execute('''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT,
                email TEXT UNIQUE,
                created_at TEXT
            )
        ''')

    # --- Migrate user_profile table ---
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_profile'")
    user_profile_table_exists = c.fetchone()

    if user_profile_table_exists:
        c.execute("PRAGMA table_info(user_profile)")
        profile_columns = {col[1]: col[2] for col in c.fetchall()}
        required_profile_columns = {
            'user_id': 'INTEGER',
            'user_type': 'TEXT',
            'savings_goal': 'REAL',
            'risk_tolerance': 'TEXT'
        }
        if 'user_id' not in profile_columns:
            c.execute('''
                CREATE TABLE user_profile_new (
                    user_id INTEGER PRIMARY KEY,
                    user_type TEXT,
                    savings_goal REAL,
                    risk_tolerance TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            old_profile_columns = list(profile_columns.keys())
            common_profile_columns = [col for col in old_profile_columns if col in ['user_type', 'savings_goal', 'risk_tolerance']]
            select_profile_columns_str = ', '.join(common_profile_columns) if common_profile_columns else 'rowid'
            c.execute(f'SELECT {select_profile_columns_str} FROM user_profile')
            old_profile_data = c.fetchall()
            c.execute('SELECT id FROM users')
            user_ids = [row[0] for row in c.fetchall()]
            for i, row in enumerate(old_profile_data):
                row_dict = dict(zip(common_profile_columns, row)) if common_profile_columns else {}
                user_id = user_ids[i] if i < len(user_ids) else None
                if user_id is None:
                    continue
                user_type = row_dict.get('user_type', 'general')
                savings_goal = row_dict.get('savings_goal', 0.0)
                risk_tolerance = row_dict.get('risk_tolerance', 'moderate')
                c.execute('''
                    INSERT INTO user_profile_new (user_id, user_type, savings_goal, risk_tolerance)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, user_type, savings_goal, risk_tolerance))
            c.execute('DROP TABLE user_profile')
            c.execute('ALTER TABLE user_profile_new RENAME TO user_profile')
    else:
        c.execute('''
            CREATE TABLE user_profile (
                user_id INTEGER PRIMARY KEY,
                user_type TEXT,
                savings_goal REAL,
                risk_tolerance TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

    # --- Migrate transactions table ---
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'")
    transactions_table_exists = c.fetchone()

    if transactions_table_exists:
        c.execute("PRAGMA table_info(transactions)")
        transaction_columns = {col[1]: col[2] for col in c.fetchall()}
        required_transaction_columns = {
            'id': 'INTEGER',
            'user_id': 'INTEGER',
            'tdate': 'TEXT',
            'ttype': 'TEXT',
            'category': 'TEXT',
            'amount': 'REAL',
            'note': 'TEXT'
        }
        if 'user_id' not in transaction_columns:
            c.execute('''
                CREATE TABLE transactions_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    tdate TEXT,
                    ttype TEXT,
                    category TEXT,
                    amount REAL,
                    note TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            old_transaction_columns = list(transaction_columns.keys())
            common_transaction_columns = [col for col in old_transaction_columns if col in ['id', 'tdate', 'ttype', 'category', 'amount', 'note']]
            select_transaction_columns_str = ', '.join(common_transaction_columns) if common_transaction_columns else 'rowid'
            c.execute(f'SELECT {select_transaction_columns_str} FROM transactions')
            old_transaction_data = c.fetchall()
            c.execute('SELECT id FROM users LIMIT 1')
            default_user = c.fetchone()
            default_user_id = default_user[0] if default_user else None
            for row in old_transaction_data:
                row_dict = dict(zip(common_transaction_columns, row)) if common_transaction_columns else {}
                transaction_id = row_dict.get('id', None)
                tdate = row_dict.get('tdate', datetime.utcnow().isoformat())
                ttype = row_dict.get('ttype', '')
                category = row_dict.get('category', '')
                amount = row_dict.get('amount', 0.0)
                note = row_dict.get('note', '')
                if default_user_id:
                    c.execute('''
                        INSERT INTO transactions_new (id, user_id, tdate, ttype, category, amount, note)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (transaction_id, default_user_id, tdate, ttype, category, amount, note))
            c.execute('DROP TABLE transactions')
            c.execute('ALTER TABLE transactions_new RENAME TO transactions')
    else:
        c.execute('''
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                tdate TEXT,
                ttype TEXT,
                category TEXT,
                amount REAL,
                note TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

    # --- Migrate holdings table ---
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='holdings'")
    holdings_table_exists = c.fetchone()

    if holdings_table_exists:
        c.execute("PRAGMA table_info(holdings)")
        holdings_columns = {col[1]: col[2] for col in c.fetchall()}
        required_holdings_columns = {
            'id': 'INTEGER',
            'user_id': 'INTEGER',
            'symbol': 'TEXT',
            'shares': 'REAL',
            'avg_price': 'REAL',
            'added_at': 'TEXT'
        }
        if 'user_id' not in holdings_columns:
            c.execute('''
                CREATE TABLE holdings_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    symbol TEXT NOT NULL,
                    shares REAL NOT NULL,
                    avg_price REAL,
                    added_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            old_holdings_columns = list(holdings_columns.keys())
            common_holdings_columns = [col for col in old_holdings_columns if col in ['id', 'symbol', 'shares', 'avg_price', 'added_at']]
            select_holdings_columns_str = ', '.join(common_holdings_columns) if common_holdings_columns else 'rowid'
            c.execute(f'SELECT {select_holdings_columns_str} FROM holdings')
            old_holdings_data = c.fetchall()
            c.execute('SELECT id FROM users LIMIT 1')
            default_user = c.fetchone()
            default_user_id = default_user[0] if default_user else None
            for row in old_holdings_data:
                row_dict = dict(zip(common_holdings_columns, row)) if common_holdings_columns else {}
                holding_id = row_dict.get('id', None)
                symbol = row_dict.get('symbol', '')
                shares = row_dict.get('shares', 0.0)
                avg_price = row_dict.get('avg_price', None)
                added_at = row_dict.get('added_at', datetime.utcnow().isoformat())
                if default_user_id:
                    c.execute('''
                        INSERT INTO holdings_new (id, user_id, symbol, shares, avg_price, added_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (holding_id, default_user_id, symbol, shares, avg_price, added_at))
            c.execute('DROP TABLE holdings')
            c.execute('ALTER TABLE holdings_new RENAME TO holdings')
    else:
        c.execute('''
            CREATE TABLE holdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                symbol TEXT NOT NULL,
                shares REAL NOT NULL,
                avg_price REAL,
                added_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

    # --- Create savings_goals table ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS savings_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            goal_name TEXT NOT NULL,
            target_amount REAL NOT NULL,
            current_amount REAL DEFAULT 0.0,
            deadline TEXT,
            note TEXT,
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    # Create config table
    c.execute('''
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(username, password, email):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        password_hash = hash_password(password)
        c.execute('INSERT INTO users (username, password_hash, email, created_at) VALUES (?, ?, ?, ?)',
                  (username, password_hash, email, datetime.utcnow().isoformat()))
        conn.commit()
        user_id = c.lastrowid
        c.execute('INSERT INTO user_profile (user_id, user_type, savings_goal, risk_tolerance) VALUES (?, ?, ?, ?)',
                  (user_id, 'general', 0.0, 'moderate'))
        conn.commit()
        return user_id, None
    except sqlite3.IntegrityError as e:
        return None, "Username or email already exists."
    finally:
        conn.close()

def login_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, password_hash FROM users WHERE username = ?', (username,))
    user = c.fetchone()
    conn.close()
    if user and user[1] == hash_password(password):
        return user[0], None
    return None, "Invalid username or password."

def set_config(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('REPLACE INTO config (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def get_config(key):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT value FROM config WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def add_holding(symbol, shares, avg_price=None):
    if not st.session_state.logged_in:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO holdings (user_id, symbol, shares, avg_price, added_at) VALUES (?, ?, ?, ?, ?)',
              (st.session_state.user_id, symbol.upper(), shares, avg_price, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def get_holdings():
    if not st.session_state.logged_in:
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query('SELECT * FROM holdings WHERE user_id = ?', conn, params=(st.session_state.user_id,))
    conn.close()
    return df

def remove_holding(row_id):
    if not st.session_state.logged_in:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM holdings WHERE id = ? AND user_id = ?', (row_id, st.session_state.user_id))
    conn.commit()
    conn.close()

def add_transaction(tdate, ttype, category, amount, note=''):
    if not st.session_state.logged_in:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO transactions (user_id, tdate, ttype, category, amount, note) VALUES (?, ?, ?, ?, ?, ?)',
              (st.session_state.user_id, tdate, ttype, category, amount, note))
    conn.commit()
    conn.close()

def get_transactions():
    if not st.session_state.logged_in:
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query('SELECT * FROM transactions WHERE user_id = ? ORDER BY tdate DESC', conn, params=(st.session_state.user_id,))
    conn.close()
    return df

def remove_transaction(row_id):
    if not st.session_state.logged_in:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM transactions WHERE id = ? AND user_id = ?', (row_id, st.session_state.user_id))
    conn.commit()
    conn.close()

def save_user_profile(user_type, savings_goal, risk_tolerance):
    if not st.session_state.logged_in:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('REPLACE INTO user_profile (user_id, user_type, savings_goal, risk_tolerance) VALUES (?, ?, ?, ?)',
              (st.session_state.user_id, user_type, savings_goal, risk_tolerance))
    conn.commit()
    conn.close()

def get_user_profile():
    if not st.session_state.logged_in:
        return {'user_type': 'general', 'savings_goal': 0.0, 'risk_tolerance': 'moderate'}
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query('SELECT * FROM user_profile WHERE user_id = ?', conn, params=(st.session_state.user_id,))
    conn.close()
    if df.empty:
        return {'user_type': 'general', 'savings_goal': 0.0, 'risk_tolerance': 'moderate'}
    return df.iloc[0].to_dict()

def add_savings_goal(goal_name, target_amount, deadline=None, note=''):
    if not st.session_state.logged_in:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO savings_goals (user_id, goal_name, target_amount, current_amount, deadline, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (st.session_state.user_id, goal_name, target_amount, 0.0, deadline, note, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def update_savings_goal(goal_id, goal_name=None, target_amount=None, current_amount=None, deadline=None, note=None):
    if not st.session_state.logged_in:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    updates = []
    params = []
    if goal_name is not None:
        updates.append('goal_name = ?')
        params.append(goal_name)
    if target_amount is not None:
        updates.append('target_amount = ?')
        params.append(target_amount)
    if current_amount is not None:
        updates.append('current_amount = ?')
        params.append(current_amount)
    if deadline is not None:
        updates.append('deadline = ?')
        params.append(deadline)
    if note is not None:
        updates.append('note = ?')
        params.append(note)
    if updates:
        params.append(goal_id)
        params.append(st.session_state.user_id)
        update_str = ', '.join(updates)
        c.execute(f'UPDATE savings_goals SET {update_str} WHERE id = ? AND user_id = ?', params)
        conn.commit()
    conn.close()

def get_savings_goals():
    if not st.session_state.logged_in:
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query('SELECT * FROM savings_goals WHERE user_id = ? ORDER BY created_at DESC', conn, params=(st.session_state.user_id,))
    conn.close()
    return df

def remove_savings_goal(goal_id):
    if not st.session_state.logged_in:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM savings_goals WHERE id = ? AND user_id = ?', (goal_id, st.session_state.user_id))
    conn.commit()
    conn.close()

# --- PRICE FETCHING ---

def fetch_price_yfinance(symbol):
    try:
        t = yf.Ticker(symbol)
        if hasattr(t, 'fast_info') and t.fast_info and 'last_price' in t.fast_info:
            return float(t.fast_info['last_price'])
        todays = t.history(period='1d')
        if not todays.empty:
            price = todays['Close'].iloc[-1]
        else:
            info = {}
            try:
                info = t.get_info() or {}
            except Exception:
                info = {}
            price = info.get('regularMarketPrice') or info.get('previousClose')
        return float(price) if price is not None else None
    except Exception:
        return None

def fetch_alpha_vantage_quote(symbol, api_key=None):
    api_key = api_key or get_config('alpha_vantage_key')
    if not api_key:
        return None
    url = 'https://www.alphavantage.co/query'
    params = {
        'function': 'GLOBAL_QUOTE',
        'symbol': symbol,
        'apikey': api_key
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        quote = data.get('Global Quote', {})
        price = quote.get('05. price')
        return float(price) if price else None
    except Exception:
        return None

# --- HISTORICAL PORTFOLIO VALUE ---

def build_portfolio_history(holdings_df, days=90):
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    if holdings_df.empty:
        return pd.DataFrame()
    df_list = []
    for _, row in holdings_df.iterrows():
        symbol = row['symbol']
        shares = row['shares']
        try:
            hist = yf.download(symbol, start=start.isoformat(), end=end.isoformat(), progress=False)
            if hist.empty:
                continue
            hist = hist[['Close']].rename(columns={'Close': symbol})
            hist[symbol] = hist[symbol] * shares
            df_list.append(hist[symbol])
        except Exception:
            continue
    if not df_list:
        return pd.DataFrame()
    combined = pd.concat(df_list, axis=1).fillna(method='ffill').fillna(0)
    combined['portfolio_value'] = combined.sum(axis=1)
    combined.index = pd.to_datetime(combined.index)
    return combined[['portfolio_value']]

# --- FEATURE 2: AI-GENERATED BUDGET SUMMARIES ---

def generate_budget_summary(transactions_df):
    if transactions_df.empty:
        return "You have no transactions logged yet. Start by adding some income and expenses to see your budget summary!"

    transactions_df = transactions_df.copy()
    transactions_df['tdate'] = pd.to_datetime(transactions_df['tdate'])
    transactions_df['month'] = transactions_df['tdate'].dt.to_period('M')
    
    summary = "### Your Budget Snapshot\n\n"
    
    total_income = transactions_df[transactions_df['ttype'].str.lower() == 'income']['amount'].sum()
    total_expenses = transactions_df[transactions_df['ttype'].str.lower() == 'expense']['amount'].sum()
    net_balance = total_income - total_expenses
    
    summary += f"**Total Income:** ₹{total_income:,.2f}\n"
    summary += f"**Total Expenses:** ₹{total_expenses:,.2f}\n"
    summary += f"**Net Balance:** ₹{net_balance:,.2f}\n"
    
    summary += "\n---\n\n"
    
    monthly_summary = transactions_df.groupby('month').agg(
        income=('amount', lambda x: x[transactions_df.loc[x.index, 'ttype'].str.lower() == 'income'].sum()),
        expenses=('amount', lambda x: x[transactions_df.loc[x.index, 'ttype'].str.lower() == 'expense'].sum())
    )
    monthly_summary['net'] = monthly_summary['income'] - monthly_summary['expenses']
    
    summary += "### Monthly Performance\n\n"
    for month, row in monthly_summary.iterrows():
        month_name = calendar.month_name[month.month]
        summary += f"**{month_name} {month.year}:** Income: ₹{row['income']:,.2f}, Expenses: ₹{row['expenses']:,.2f}, Net: ₹{row['net']:,.2f}\n"
    
    return summary

# --- FEATURE 3: SPENDING INSIGHTS AND SUGGESTIONS ---

def get_spending_insights(transactions_df):
    if transactions_df.empty or transactions_df[transactions_df['ttype'].str.lower() == 'expense'].empty:
        return "Not enough data to provide spending insights. Please log some expenses."

    expense_df = transactions_df[transactions_df['ttype'].str.lower() == 'expense'].copy()
    expense_df['category'] = expense_df['category'].str.lower()
    
    insights = "### Your Spending Insights & Tips\n\n"
    
    total_expenses = expense_df['amount'].sum()
    category_spending = expense_df.groupby('category')['amount'].sum().sort_values(ascending=False)
    
    top_category = category_spending.index[0]
    top_spending = category_spending.iloc[0]
    percentage = (top_spending / total_expenses) * 100 if total_expenses > 0 else 0
    
    insights += f"**Top Spending Category:** You've spent a significant **₹{top_spending:,.2f}** on **{top_category.capitalize()}**, which is about **{percentage:.1f}%** of your total expenses. This is a great area to focus on for potential savings.\n\n"
    
    if percentage > 40:
        insights += "⚠️ **Urgent Suggestion:** Your spending in this single category is very high. It might be a good idea to create a specific budget for this area to get it under control.\n\n"
    elif percentage > 20:
        insights += "💡 **Smart Tip:** Consider a spending audit for this category. Maybe there are subscription services you don't use or cheaper alternatives you could switch to.\n\n"
    
    return insights

# --- RULE-BASED FINANCE Q&A ---

def get_finance_response(user_message):
    if not st.session_state.logged_in:
        return "Please log in to get personalized financial advice."

    # Fetch user data for context
    user_profile = get_user_profile()
    holdings = get_holdings()
    transactions = get_transactions()
    savings_goals = get_savings_goals()

    # Calculate key metrics
    total_value = 0
    if not holdings.empty:
        total_value = sum(fetch_price_yfinance(r['symbol']) * r['shares'] for _, r in holdings.iterrows() if fetch_price_yfinance(r['symbol']))
    total_income = transactions[transactions['ttype'].str.lower() == 'income']['amount'].sum() if not transactions.empty else 0
    total_expenses = transactions[transactions['ttype'].str.lower() == 'expense']['amount'].sum() if not transactions.empty else 0
    net_balance = total_income - total_expenses
    total_savings_target = savings_goals['target_amount'].sum() if not savings_goals.empty else 0
    total_saved = savings_goals['current_amount'].sum() if not savings_goals.empty else 0

    # Rule-based response dictionary
    finance_rules = [
        {
            "patterns": [r"\b(budget|budgeting|spending|expenses)\b", r"how.*(manage|plan).*money"],
            "response": lambda: f"Your current budget shows ₹{total_income:,.2f} in income and ₹{total_expenses:,.2f} in expenses, with a net balance of ₹{net_balance:,.2f}. To manage your money, track expenses regularly and aim to save at least 20% of your income. {'Set a monthly budget for categories like groceries or utilities to stay on track.' if user_profile['user_type'] == 'student' else 'Consider allocating funds to high-priority categories and reviewing monthly.'}"
        },
        {
            "patterns": [r"\b(invest|investment|stocks|portfolio)\b", r"where.*invest"],
            "response": lambda: f"Your portfolio is worth ₹{total_value:,.2f}. With a {user_profile['risk_tolerance']} risk tolerance, {'stick to low-risk options like fixed deposits or blue-chip stocks' if user_profile['risk_tolerance'] == 'low' else 'consider a mix of stocks and mutual funds' if user_profile['risk_tolerance'] == 'moderate' else 'explore growth stocks or ETFs, but diversify to manage risk'}. {'Start small with mutual funds to learn.' if user_profile['user_type'] == 'student' else 'Diversify across sectors to reduce risk.'}"
        },
        {
            "patterns": [r"\b(savings|saving|goals|emergency fund)\b", r"how.*save"],
            "response": lambda: f"You have {len(savings_goals)} savings goal(s) with a total target of ₹{total_savings_target:,.2f} and ₹{total_saved:,.2f} saved. {'Save small amounts regularly, like ₹500/month, for an emergency fund.' if user_profile['user_type'] == 'student' else 'Automate savings to reach your goals faster.'} Aim for an emergency fund covering 3-6 months of expenses."
        },
        {
            "patterns": [r"\b(financial statement|balance sheet|income statement|cash flow)\b"],
            "response": lambda: f"A financial statement summarizes your money. The balance sheet shows what you own (assets like ₹{total_value:,.2f} in investments) and owe. The income statement tracks income (₹{total_income:,.2f}) and expenses (₹{total_expenses:,.2f}). The cash flow statement shows money moving in and out. {'Think of it as tracking your pocket money and spending.' if user_profile['user_type'] == 'student' else 'Review these monthly to understand your financial health.'}"
        },
        {
            "patterns": [r"\b(risk|risk tolerance|diversification)\b"],
            "response": lambda: f"Your risk tolerance is {user_profile['risk_tolerance']}. {'Low risk means safer investments like fixed deposits, but lower returns.' if user_profile['risk_tolerance'] == 'low' else 'Moderate risk balances growth and safety with mixed investments.' if user_profile['risk_tolerance'] == 'moderate' else 'High risk allows for growth stocks but can lead to losses.'} Diversification spreads your ₹{total_value:,.2f} portfolio across assets to reduce risk."
        },
        {
            "patterns": [r"\b(roi|return on investment)\b"],
            "response": lambda: f"Return on Investment (ROI) measures profit from investments. For your portfolio (₹{total_value:,.2f}), ROI = (Current Value - Cost) / Cost. {'It’s like checking if your savings grew.' if user_profile['user_type'] == 'student' else 'Calculate ROI for each holding to assess performance.'}"
        },
        {
            "patterns": [r"\b(tax|taxes|tax planning)\b"],
            "response": lambda: f"With ₹{total_income:,.2f} in income, consider tax-saving options. {'Save in schemes like PPF to reduce taxes.' if user_profile['user_type'] == 'student' else 'Invest in ELSS mutual funds or PPF for tax deductions under Section 80C.'} Consult a tax advisor for personalized strategies."
        },
        {
            "patterns": [r".*"],
            "response": lambda: f"I’m not sure about that question. Try asking about budgeting, investments, savings, or taxes for personalized advice based on your ₹{total_value:,.2f} portfolio and ₹{net_balance:,.2f} net balance."
        }
    ]

    # Match query to rules
    user_message_lower = user_message.lower()
    for rule in finance_rules:
        for pattern in rule["patterns"]:
            if re.search(pattern, user_message_lower):
                response = rule["response"]()
                return format_text_for_user(response, user_profile['user_type'])
    
    # Fallback (shouldn’t reach here due to catch-all rule)
    return format_text_for_user("Please ask a finance-related question, like budgeting or investing.", user_profile['user_type'])

# --- DEMOGRAPHIC-AWARE COMMUNICATION ---

def format_text_for_user(text, user_type):
    if user_type == 'student':
        text = text.replace("assets", "things you own").replace("securities", "investments")
        text = text.replace("wealth accumulation", "growing your money").replace("diversification", "spreading out your money so you don't put all your eggs in one basket")
        text = text.replace("professional", "someone with a job").replace("taxable income", "the part of your income the government can tax")
        return text
    else:
        return text

# --- UI COMPONENTS ---

def login_page():
    st.header("Login")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
        if submitted:
            user_id, error = login_user(username, password)
            if user_id:
                st.session_state.logged_in = True
                st.session_state.user_id = user_id
                st.success("Logged in successfully!")
                safe_rerun()
            else:
                st.error(error)

def register_page():
    st.header("Register")
    with st.form("register_form"):
        username = st.text_input("Username")
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        confirm_password = st.text_input("Confirm Password", type="password")
        submitted = st.form_submit_button("Register")
        if submitted:
            if password != confirm_password:
                st.error("Passwords do not match.")
            elif len(password) < 6:
                st.error("Password must be at least 6 characters long.")
            elif not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
                st.error("Invalid email format.")
            else:
                user_id, error = register_user(username, password, email)
                if user_id:
                    st.session_state.logged_in = True
                    st.session_state.user_id = user_id
                    st.success("Registered and logged in successfully!")
                    safe_rerun()
                else:
                    st.error(error)

def settings_page():
    if not st.session_state.logged_in:
        st.warning("Please log in to access settings.")
        return
    
    st.header('Settings')
    user_profile = get_user_profile()
    with st.form("user_profile_form"):
        user_type = st.selectbox(
            'I am a...',
            ('student', 'professional', 'general'),
            index=('student', 'professional', 'general').index(user_profile.get('user_type', 'general'))
        )
        savings_goal = st.number_input('Overall Savings Goal (optional, e.g. ₹50,000)', min_value=0.0, value=user_profile.get('savings_goal', 0.0))
        risk_tolerance = st.selectbox(
            'My Investment Risk Tolerance is...',
            ('low', 'moderate', 'high'),
            index=('low', 'moderate', 'high').index(user_profile.get('risk_tolerance', 'moderate'))
        )
        profile_submitted = st.form_submit_button("Save Profile")
        if profile_submitted:
            save_user_profile(user_type, savings_goal, risk_tolerance)
            st.success("Profile saved successfully!")
            safe_rerun()

    st.markdown('---')
    st.write('You can optionally provide an Alpha Vantage API key to fetch quotes from Alpha Vantage instead of yfinance.')
    existing_key = get_config('alpha_vantage_key') or ""
    av_key = st.text_input('Alpha Vantage API Key (optional - saved securely in app DB)', value=existing_key, type='password', key='av_settings')
    if st.button('Save Alpha Vantage Key'):
        if av_key:
            set_config('alpha_vantage_key', av_key)
            st.success('Alpha Vantage key saved.')
        else:
            st.info('No key entered. Existing key (if any) will remain.')

    st.info('If you do not provide an Alpha Vantage key, yfinance will be used by default.')

def portfolio_page():
    if not st.session_state.logged_in:
        st.warning("Please log in to access your portfolio.")
        return
    
    st.header('Portfolio Tracker')
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader('Add holding')
        symbol = st.text_input('Symbol (e.g. AAPL, TCS.NS)', key='sym_input')
        shares = st.number_input('Shares', min_value=0.0, format='%f', step=1.0)
        avg_price = st.number_input('Avg. price (optional)', min_value=0.0, format='%f', step=1.0)
        if st.button('Add'):
            if symbol and shares > 0:
                add_holding(symbol, shares, avg_price if avg_price > 0 else None)
                st.success(f'Added {shares} of {symbol.upper()}')
                safe_rerun()
            else:
                st.error('Please provide a symbol and shares > 0')

        st.subheader('Quick lookup')
        quick_sym = st.text_input('Lookup symbol', key='quick')
        av_key_session = get_config('alpha_vantage_key')
        api_options = ['yfinance']
        if av_key_session:
            api_options.append('alpha_vantage')
        api_choice = st.selectbox('Price source', api_options, key='api_choice_quick')
        
        if st.button('Get price', key='get_price'):
            if not quick_sym:
                st.error('Enter symbol')
            else:
                price = None
                if api_choice == 'yfinance':
                    price = fetch_price_yfinance(quick_sym)
                elif api_choice == 'alpha_vantage' and av_key_session:
                    price = fetch_alpha_vantage_quote(quick_sym, av_key_session)
                
                if price is None:
                    st.warning('Price not found or API key is invalid.')
                else:
                    st.metric(label=f'{quick_sym.upper()} price', value=f"₹{price:.2f}")

    with col2:
        st.subheader('Your holdings')
        holdings = get_holdings()
        if holdings.empty:
            st.info('No holdings yet — add one on the left.')
        else:
            prices = [fetch_price_yfinance(r['symbol']) for _, r in holdings.iterrows()]
            holdings['price'] = [p if p is not None else 0.0 for p in prices]
            holdings['market_value'] = holdings['shares'] * holdings['price']
            total_value = holdings['market_value'].sum()
            st.metric('Total Portfolio Value', f"₹{total_value:,.2f}")

            display_df = holdings[['id', 'symbol', 'shares', 'avg_price', 'price', 'market_value']].rename(columns={'id': 'ID', 'avg_price': 'Avg. Price', 'market_value': 'Market Value'})
            st.dataframe(display_df.set_index('ID'))

            st.subheader('Remove a holding')
            to_remove = st.selectbox('Select ID to remove', options=holdings['id'].tolist())
            if st.button('Remove'):
                remove_holding(to_remove)
                st.success('Removed')
                safe_rerun()

            st.subheader('Portfolio history')
            days = st.slider('Days', min_value=7, max_value=365, value=90)
            hist = build_portfolio_history(holdings, days=days)
            if hist.empty:
                st.info('No historical data available for holdings')
            else:
                fig = px.line(hist.reset_index(), x=hist.index, y='portfolio_value', title='Portfolio Value Over Time')
                st.plotly_chart(fig, use_container_width=True)

            st.subheader('Portfolio Diversification 📊')
            if not holdings.empty:
                @st.cache_data
                def get_sectors(symbols):
                    sectors = {}
                    for symbol in symbols:
                        try:
                            ticker = yf.Ticker(symbol)
                            info = {}
                            try:
                                info = ticker.get_info() or {}
                            except Exception:
                                info = {}
                            sector = info.get('sector', 'Unknown')
                            sectors[symbol] = sector or 'Unknown'
                        except Exception:
                            sectors[symbol] = 'Unknown'
                    return sectors

                holdings_symbols = holdings['symbol'].tolist()
                sector_map = get_sectors(holdings_symbols)
                holdings['sector'] = holdings['symbol'].map(sector_map)

                sector_allocation = holdings.groupby('sector')['market_value'].sum().reset_index()
                sector_allocation.columns = ['Sector', 'Market Value']

                fig_pie = px.pie(
                    sector_allocation,
                    values='Market Value',
                    names='Sector',
                    title='Portfolio Breakdown by Sector'
                )
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info('Add some holdings to see your portfolio diversification.')

            st.subheader('Performance Benchmark vs. Nifty 50 📈')
            index_symbol = '^NSEI'
            if not holdings.empty:
                portfolio_hist = build_portfolio_history(holdings, days=90)
                
                if not portfolio_hist.empty:
                    try:
                        index_hist = yf.download(index_symbol, start=portfolio_hist.index.min().isoformat(), end=portfolio_hist.index.max().isoformat(), progress=False)
                        if not index_hist.empty:
                            portfolio_hist = portfolio_hist.copy()
                            portfolio_hist['Normalized Portfolio Value'] = (portfolio_hist['portfolio_value'] / portfolio_hist['portfolio_value'].iloc[0]) * 100
                            index_hist = index_hist.copy()
                            index_hist['Normalized Index Value'] = (index_hist['Close'] / index_hist['Close'].iloc[0]) * 100

                            combined_df = pd.DataFrame({
                                'Date': portfolio_hist.index,
                                'Portfolio': portfolio_hist['Normalized Portfolio Value'].values
                            })
                            index_series = index_hist['Normalized Index Value']
                            index_series = index_series.reindex(pd.to_datetime(portfolio_hist.index)).fillna(method='ffill').values
                            combined_df['Nifty 50'] = index_series

                            fig_benchmark = px.line(combined_df, x='Date', y=['Portfolio', 'Nifty 50'], title=f"Portfolio Performance vs. {index_symbol}")
                            fig_benchmark.update_layout(legend_title_text='Asset')
                            st.plotly_chart(fig_benchmark, use_container_width=True)
                        else:
                            st.warning(f"Could not fetch historical data for {index_symbol}.")
                    except Exception:
                        st.warning("Could not perform benchmarking due to an error fetching index data.")
                else:
                    st.info('Not enough historical data to perform benchmarking.')

def budget_page():
    if not st.session_state.logged_in:
        st.warning("Please log in to access budget and transactions.")
        return
    
    st.header('Budget & Transactions')
    col1, col2 = st.columns([1, 2])
    
    with col1:
        with st.form('trans_form'):
            tdate = st.date_input('Date', value=datetime.today())
            ttype = st.selectbox('Type', ['Income', 'Expense'])
            category = st.text_input('Category (e.g. Salary, Groceries)')
            amount = st.number_input('Amount', min_value=0.0, format='%f')
            note = st.text_input('Note (optional)')
            submitted = st.form_submit_button('Add transaction')
            if submitted:
                if amount > 0 and category:
                    add_transaction(tdate.isoformat(), ttype, category, amount, note)
                    st.success('Transaction added')
                    safe_rerun()
                else:
                    st.error('Amount must be greater than 0 and category cannot be empty.')
    
    with col2:
        st.subheader('Recent transactions')
        tx = get_transactions()
        if tx.empty:
            st.info('No transactions yet')
        else:
            tx['tdate'] = pd.to_datetime(tx['tdate']).dt.date
            tx['S.No.'] = range(1, len(tx) + 1)
            st.dataframe(tx[['S.No.', 'tdate', 'ttype', 'category', 'amount', 'note']]
                         .rename(columns={'tdate': 'Date', 'ttype': 'Type', 'category': 'Category', 'amount': 'Amount', 'note': 'Note'})
                         .set_index('S.No.'))

        st.subheader('Delete a transaction')
        if not tx.empty:
            tx_ids = tx['id'].tolist()
            to_remove = st.selectbox('Select ID to delete', options=['Select ID'] + tx_ids)
            if st.button('Delete') and to_remove != 'Select ID':
                remove_transaction(to_remove)
                st.success('Transaction deleted successfully.')
                safe_rerun()
        else:
            st.info('No transactions to delete.')

    st.markdown('---')
    st.header('Budget Summary & Insights')
    
    tx_all = get_transactions()
    
    if not tx_all.empty:
        budget_summary = generate_budget_summary(tx_all)
        spending_insights = get_spending_insights(tx_all)
        st.markdown(budget_summary)
        st.markdown('---')
        st.markdown(spending_insights)
    else:
        st.info("Log some transactions to get a summary and insights.")
    
    st.markdown('---')
    
    st.subheader("Spending from Salary Breakdown")
    expenses_df = tx_all[(tx_all['ttype'].str.lower() == 'expense')]
    total_income = tx_all[tx_all['ttype'].str.lower() == 'income']['amount'].sum()
    total_expenses = expenses_df['amount'].sum()
    if not expenses_df.empty:
        expenses_df['category'] = expenses_df['category'].str.lower()
        spending_by_category = expenses_df.groupby('category')['amount'].sum()
        
        remaining_balance = total_income - total_expenses
        if remaining_balance > 0:
            spending_by_category = pd.concat([spending_by_category, pd.Series([remaining_balance], index=['Remaining'])])
        
        spending_df = spending_by_category.reset_index()
        spending_df.columns = ['Category', 'Amount']
        
        fig = px.pie(
            spending_df,
            values='Amount',
            names='Category',
            title='Your Spending from Income'
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No expenses found to generate a pie chart.")

def savings_page():
    if not st.session_state.logged_in:
        st.warning("Please log in to access your savings goals.")
        return
    
    st.header('Savings Goals')
    st.info("Manage your savings targets here. Set goals for things like a trip, a new gadget, or an emergency fund, and track your progress.")
    
    # --- Add New Savings Goal ---
    st.subheader('Add New Savings Goal')
    with st.form('savings_goal_form'):
        goal_name = st.text_input('Goal Name (e.g. Vacation, Emergency Fund)')
        target_amount = st.number_input('Target Amount (₹)', min_value=0.0, format='%f')
        deadline = st.date_input('Deadline (optional)', value=None, min_value=datetime.today())
        note = st.text_input('Note (optional)')
        submitted = st.form_submit_button('Add Goal')
        if submitted:
            if goal_name and target_amount > 0:
                add_savings_goal(goal_name, target_amount, deadline.isoformat() if deadline else None, note)
                st.success(f'Added savings goal: {goal_name}')
                safe_rerun()
            else:
                st.error('Goal name and target amount are required, and target amount must be greater than 0.')

    # --- View and Manage Savings Goals ---
    st.markdown('---')
    st.subheader('Your Savings Goals')
    goals = get_savings_goals()
    if goals.empty:
        st.info('No savings goals yet. Add one above!')
    else:
        # Calculate net savings from transactions
        transactions = get_transactions()
        total_income = transactions[transactions['ttype'].str.lower() == 'income']['amount'].sum() if not transactions.empty else 0
        total_expenses = transactions[transactions['ttype'].str.lower() == 'expense']['amount'].sum() if not transactions.empty else 0
        net_savings = total_income - total_expenses
        
        # Distribute net savings evenly across goals for simplicity (can be customized later)
        num_goals = len(goals)
        if num_goals > 0 and net_savings > 0:
            allocated_per_goal = net_savings / num_goals
            goals['current_amount'] = allocated_per_goal
            for _, row in goals.iterrows():
                update_savings_goal(row['id'], current_amount=allocated_per_goal)
        else:
            goals['current_amount'] = 0.0

        goals['progress'] = goals.apply(lambda x: min((x['current_amount'] / x['target_amount']) * 100, 100) if x['target_amount'] > 0 else 0, axis=1)
        goals['deadline'] = pd.to_datetime(goals['deadline']).dt.date
        display_df = goals[['id', 'goal_name', 'target_amount', 'current_amount', 'progress', 'deadline', 'note']].rename(
            columns={'id': 'ID', 'goal_name': 'Goal', 'target_amount': 'Target (₹)', 'current_amount': 'Saved (₹)', 'progress': 'Progress (%)', 'deadline': 'Deadline', 'note': 'Note'}
        )
        st.dataframe(display_df.set_index('ID'))

        # --- Edit Savings Goal ---
        st.subheader('Edit Savings Goal')
        goal_ids = goals['id'].tolist()
        selected_goal = st.selectbox('Select Goal to Edit', options=['Select Goal'] + goal_ids)
        if selected_goal != 'Select Goal':
            goal_data = goals[goals['id'] == int(selected_goal)].iloc[0]
            with st.form('edit_savings_goal_form'):
                edit_goal_name = st.text_input('Goal Name', value=goal_data['goal_name'])
                edit_target_amount = st.number_input('Target Amount (₹)', min_value=0.0, value=float(goal_data['target_amount']), format='%f')
                edit_deadline = st.date_input('Deadline (optional)', value=pd.to_datetime(goal_data['deadline']) if pd.notnull(goal_data['deadline']) else None, min_value=datetime.today())
                edit_note = st.text_input('Note (optional)', value=goal_data['note'] if pd.notnull(goal_data['note']) else '')
                edit_submitted = st.form_submit_button('Update Goal')
                if edit_submitted:
                    if edit_goal_name and edit_target_amount > 0:
                        update_savings_goal(
                            int(selected_goal),
                            goal_name=edit_goal_name,
                            target_amount=edit_target_amount,
                            deadline=edit_deadline.isoformat() if edit_deadline else None,
                            note=edit_note
                        )
                        st.success(f'Updated savings goal: {edit_goal_name}')
                        safe_rerun()
                    else:
                        st.error('Goal name and target amount are required, and target amount must be greater than 0.')

        # --- Delete Savings Goal ---
        st.subheader('Delete Savings Goal')
        to_remove = st.selectbox('Select Goal ID to Delete', options=['Select ID'] + goal_ids)
        if st.button('Delete Goal') and to_remove != 'Select ID':
            remove_savings_goal(int(to_remove))
            st.success('Savings goal deleted successfully.')
            safe_rerun()

        # --- Visualize Progress ---
        st.subheader('Savings Progress')
        for _, row in goals.iterrows():
            st.write(f"**{row['goal_name']}** (Target: ₹{row['target_amount']:,.2f})")
            progress = min((row['current_amount'] / row['target_amount']) if row['target_amount'] > 0 else 0, 1)
            st.progress(progress)
            st.write(f"Saved: ₹{row['current_amount']:,.2f} ({row['progress']:.1f}% of target)")
            if pd.notnull(row['deadline']):
                days_left = (pd.to_datetime(row['deadline']) - datetime.today()).days
                st.write(f"Deadline: {row['deadline']} ({days_left} days left)" if days_left >= 0 else f"Deadline: {row['deadline']} (Overdue by {abs(days_left)} days)")
            st.markdown('---')

# --- NEWS INTEGRATION (mock) ---

def fetch_news(symbol):
    mock_news = {
        "AAPL": [
            {"title": "Apple unveils new iPhone model with advanced camera features.", "source": "TechCrunch", "publishedAt": "2023-10-27T10:00:00Z"},
        ],
        "MSFT": [
            {"title": "Microsoft announces major AI integration into Windows.", "source": "The Verge", "publishedAt": "2023-10-27T09:00:00Z"},
        ],
        "TCS.NS": [
            {"title": "TCS reports robust revenue growth, exceeding expectations.", "source": "Economic Times", "publishedAt": "2023-10-27T08:00:00Z"},
        ]
    }
    return mock_news.get(symbol.upper(), [])

def market_lookup_page():
    if not st.session_state.logged_in:
        st.warning("Please log in to access market lookup.")
        return
    
    st.header('Market Lookup & News')
    user_profile = get_user_profile()
    user_type = user_profile['user_type']
    
    if user_type == 'student':
        st.info("Hey! The market can be tricky. Look up symbols you've heard about to learn how they've performed.")
    else:
        st.info("Quickly look up stock prices and historical data.")

    symbol = st.text_input('Ticker symbol (e.g. AAPL, MSFT, TCS.NS)')
    
    if st.button('Lookup'):
        if not symbol:
            st.error('Enter a ticker symbol')
        else:
            price = fetch_price_yfinance(symbol)
            if price:
                st.metric(f'{symbol.upper()} price', f"₹{price:.2f}")
                hist = yf.download(symbol, period='60d', progress=False)
                if not hist.empty:
                    # Simplify column names if MultiIndex exists
                    if isinstance(hist.columns, pd.MultiIndex):
                        hist.columns = [col[0] if isinstance(col, tuple) else col for col in hist.columns]
                    # Reset index to make Date a column
                    hist = hist.reset_index()
                    # Ensure 'Date' and 'Close' columns exist
                    if 'Date' in hist.columns and 'Close' in hist.columns:
                        fig = px.line(hist, x='Date', y='Close', title=f'{symbol.upper()} - Last 60 days')
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.warning('Expected columns (Date, Close) not found in data.')
                else:
                    st.warning('Price not found for that symbol')
                st.subheader(f"News for {symbol.upper()}")
                news_articles = fetch_news(symbol)
                if news_articles:
                    for article in news_articles:
                        st.write(f"**[{article['title']}]** ({article['source']})")
                else:
                    st.info(f"No recent news found for {symbol.upper()}.")
            else:
                st.warning('Price not found for that symbol. Cannot fetch news without a valid symbol.')

# --- PERSONALIZED GUIDANCE ---

def get_personalized_guidance(user_profile, holdings_df, transactions_df):
    profile = user_profile or get_user_profile()
    guidance = f"### Personalized Financial Advice\n\n"

    user_type = profile['user_type']
    if user_type == 'student':
        guidance += "As a **student**, your focus should be on building good financial habits. Prioritize a small emergency fund and learn about low-cost investing options.\n\n"
    elif user_type == 'professional':
        guidance += "As a **professional**, you're likely focused on wealth accumulation. Consider optimizing your tax strategy and diversifying your investment portfolio.\n\n"
    else:
        guidance += "Here's some general financial advice. Start by setting clear financial goals for yourself.\n\n"

    guidance += "---\n\n"

    transactions_df = transactions_df if transactions_df is not None else get_transactions()
    total_income = transactions_df[transactions_df['ttype'].str.lower() == 'income']['amount'].sum() if not transactions_df.empty else 0
    total_expenses = transactions_df[transactions_df['ttype'].str.lower() == 'expense']['amount'].sum() if not transactions_df.empty else 0
    net_balance = total_income - total_expenses

    if net_balance > 0 and total_income > 0:
        savings_rate = (net_balance / total_income) * 100
        guidance += f"Based on your transactions, you have a **savings rate of {savings_rate:.1f}%**. This is a great start! Try to increase this percentage incrementally. Remember, even a little saved each month adds up over time.\n\n"
    else:
        guidance += "It looks like your expenses are close to or exceeding your income. Focus on identifying and reducing unnecessary expenses before focusing on large-scale investments.\n\n"

    holdings_df = holdings_df.copy() if holdings_df is not None else pd.DataFrame()
    if not holdings_df.empty and 'market_value' not in holdings_df.columns:
        prices = [fetch_price_yfinance(r['symbol']) for _, r in holdings_df.iterrows()]
        holdings_df['price'] = [p if p is not None else 0.0 for p in prices]
        holdings_df['market_value'] = holdings_df['shares'] * holdings_df['price']

    holdings_value = holdings_df['market_value'].sum() if not holdings_df.empty else 0
    if holdings_value > 0:
        risk_tolerance = profile.get('risk_tolerance', 'moderate')
        if risk_tolerance == 'low':
            guidance += "With a **low risk tolerance**, you might prefer stable, dividend-paying stocks or mutual funds that focus on large, established companies.\n\n"
        elif risk_tolerance == 'moderate':
            guidance += "With a **moderate risk tolerance**, a mix of stable and growth-oriented stocks could be a good fit. Diversification across different sectors is key.\n\n"
        elif risk_tolerance == 'high':
            guidance += "With a **high risk tolerance**, you're in a position to explore high-growth stocks, small-cap companies, or even some alternative investments. Just remember to only invest what you can afford to lose.\n\n"

    savings_goals = get_savings_goals()
    if not savings_goals.empty:
        total_target = savings_goals['target_amount'].sum()
        total_saved = savings_goals['current_amount'].sum()
        guidance += f"You have {len(savings_goals)} savings goal(s) with a total target of ₹{total_target:,.2f}. You've saved ₹{total_saved:,.2f} so far. Keep allocating funds to your goals on the Savings page!\n\n"

    if total_income > 500000:
        guidance += "💰 **Tax Tip:** Your income level suggests you should be mindful of tax planning. Consider investing in tax-saving instruments like ELSS mutual funds or other government-backed schemes to reduce your taxable income.\n\n"

    return guidance

# --- MAIN APP FUNCTION ---

def main():
    st.set_page_config(page_title="Personal Finance App", layout="wide")
    init_db()

    if not st.session_state.logged_in:
        st.title("📊 Personal Finance App")
        st.markdown("Please log in or register to access your personal finance dashboard.")

        tab1, tab2 = st.tabs(["Login", "Register"])
        with tab1:
            login_page()
        with tab2:
            register_page()
        return

    st.title("📊 Personal Finance App")
    user_profile = get_user_profile()

    st.sidebar.markdown(format_text_for_user(
        "Hello! 👋 This is your personal financial assistant. Navigate through the sections to track your portfolio, manage your budget, savings goals, and get personalized insights.",
        user_profile['user_type']
    ))
    st.sidebar.markdown('---')

    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.user_id = None
        st.session_state.messages = []
        st.success("Logged out successfully!")
        safe_rerun()

    # Sidebar menu with bullet button options
    menu_options = ["Dashboard", "Portfolio", "Budget & Transactions", "Savings", "Market Lookup", "Settings"]
    menu = st.sidebar.radio("Menu", menu_options, format_func=lambda x: f"• {x}")

    if menu == 'Dashboard':
        st.header("Your Financial Dashboard")
        st.info("Ask about budgeting, investments, savings, taxes, or financial statements for personalized advice!")
        
        tx_all = get_transactions()
        holdings_df = get_holdings()

        if not holdings_df.empty and 'market_value' not in holdings_df.columns:
            prices = [fetch_price_yfinance(r['symbol']) for _, r in holdings_df.iterrows()]
            holdings_df['price'] = [p if p is not None else 0.0 for p in prices]
            holdings_df['market_value'] = holdings_df['shares'] * holdings_df['price']

        savings_goal = user_profile.get('savings_goal', 0.0)
        if savings_goal > 0:
            total_income = tx_all[tx_all['ttype'].str.lower() == 'income']['amount'].sum() if not tx_all.empty else 0
            total_expenses = tx_all[tx_all['ttype'].str.lower() == 'expense']['amount'].sum() if not tx_all.empty else 0
            net_balance = total_income - total_expenses
            progress = net_balance / savings_goal if savings_goal > 0 else 0
            progress = max(0, min(1, progress))

            st.subheader(f"Overall Savings Goal (from Profile): ₹{savings_goal:,.2f}")
            st.progress(progress)

            if net_balance < 0:
                st.write(f"You have a current deficit of **₹{abs(net_balance):,.2f}** towards your overall goal of **₹{savings_goal:,.2f}**.")
            else:
                st.write(f"You've saved **₹{net_balance:,.2f}** towards your overall goal of **₹{savings_goal:,.2f}**.")

            if progress >= 1:
                st.balloons()
                st.success("🎉 Congratulations! You have reached your overall savings goal!")

        st.markdown('---')
        st.markdown(get_personalized_guidance(user_profile, holdings_df, tx_all))

        st.markdown('---')
        st.subheader("Ask your Financial Assistant")

        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if prompt := st.chat_input("Ask a finance question (e.g., 'How do I budget?' or 'What’s ROI?')"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                response = get_finance_response(prompt)
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})

    elif menu == 'Portfolio':
        portfolio_page()
    elif menu == 'Budget & Transactions':
        budget_page()
    elif menu == 'Savings':
        savings_page()
    elif menu == 'Market Lookup':
        market_lookup_page()
    elif menu == 'Settings':
        settings_page()

if __name__ == "__main__":
    main()