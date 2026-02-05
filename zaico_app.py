#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zaico 在庫確認アプリ - 完全版
バージョン: v3.0 FINAL
更新日: 2026-02-05

機能:
- PDFアップロード: 受注票から品番と数量を自動抽出
- 手動入力: 品番と数量を手動で追加
- 在庫確認: Zaico APIで在庫を確認
- 関連部品検索: サイズ表記なし部品(共通部品)も含めて検索
"""

from flask import Flask, request, jsonify, render_template
import os
import requests
import re
import pdfplumber
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Zaico API設定
ZAICO_API_URL = 'https://web.zaico.co.jp/api/v1/inventories'
ZAICO_TOKEN = os.environ.get('ZAICO_TOKEN', None)

# サイズパターン
SIZE_PATTERNS = [
    r'(\d+)\s*mm',
    r'(\d+)MM',
    r'φ\s*(\d+)',
    r'(\d+)\s*A',
    r'\(\s*(\d+)/(\d+)\s*\)',
    r'1/2', r'3/8', r'5/8', r'3/4',
]

INCH_TO_MM = {
    '1/2': 13,
    '3/8': 10,
    '5/8': 16,
    '3/4': 20,
    '1': 25
}

# ===========================
# ヘルパー関数
# ===========================

def get_item_code(item):
    """optional_attributes から品番を取得"""
    for attr in item.get('optional_attributes', []):
        if attr.get('name') == '品番':
            return attr.get('value')
    return None

def extract_sizes_from_name(item_name):
    """品名からサイズを抽出 (mm単位)"""
    sizes = set()
    
    for pattern in SIZE_PATTERNS:
        matches = re.findall(pattern, item_name)
        for match in matches:
            if isinstance(match, tuple):
                fraction = f'{match[0]}/{match[1]}'
                if fraction in INCH_TO_MM:
                    sizes.add(INCH_TO_MM[fraction])
            elif match in INCH_TO_MM:
                sizes.add(INCH_TO_MM[match])
            elif match.isdigit():
                sizes.add(int(match))
    
    return sorted(sizes)

def has_size_notation(item_name):
    """サイズ表記があるかチェック"""
    for pattern in SIZE_PATTERNS:
        if re.search(pattern, item_name):
            return True
    return False

def get_category_from_code(item_code):
    """品番から分類コードを取得 (最初の4桁)"""
    if not item_code:
        return None
    match = re.match(r'^(\d{4})', item_code)
    return match.group(1) if match else None

def get_all_inventory_data():
    """Zaico APIで全在庫データを取得 (ページネーション対応)"""
    if not ZAICO_TOKEN:
        return [], 'トークンが設定されていません'
    
    all_inventory = []
    page = 1
    per_page = 1000
    
    try:
        headers = {
            'Authorization': f'Bearer {ZAICO_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        while True:
            response = requests.get(
                ZAICO_API_URL,
                headers=headers,
                params={'per_page': per_page, 'page': page}
            )
            response.raise_for_status()
            
            data = response.json()
            
            # レスポンスが list か dict かを判定
            if isinstance(data, list):
                items = data
            else:
                items = data.get('inventories', [])
            
            if not items:
                break
            
            all_inventory.extend(items)
            
            if len(items) < per_page:
                break
            
            page += 1
        
        return all_inventory, None
        
    except requests.exceptions.RequestException as e:
        return [], str(e)

def extract_hinban_from_pdf(pdf_file):
    """
    PDFから品番と数量を抽出
    pdfplumberの表データから抽出
    """
    items = []
    
    try:
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                
                for table in tables:
                    current_hinban = None
                    
                    for row in table:
                        # 品番を検出
                        for cell in row:
                            if cell and '品番/図番' in str(cell):
                                hinban_match = re.search(r'(\d{4}-\d{2}-\d{2,3})', str(cell))
                                if hinban_match:
                                    current_hinban = hinban_match.group(1)
                        
                        # 数量を検出 (品番の次の行で探す)
                        if current_hinban:
                            for cell in row:
                                if cell and '数量' in str(cell):
                                    quantity_match = re.search(r'数量\s*\n?\s*(\d+)', str(cell))
                                    if quantity_match:
                                        quantity = int(quantity_match.group(1))
                                        items.append({
                                            'hinban': current_hinban,
                                            'quantity': quantity
                                        })
                                        current_hinban = None
                                        break
    except Exception as e:
        print(f"PDF抽出エラー: {e}")
    
    return items

# ===========================
# ルート
# ===========================

@app.route('/')
def index():
    """メインページ"""
    return render_template('index.html')

@app.route('/set_token', methods=['POST'])
def set_token():
    """トークンを設定"""
    global ZAICO_TOKEN
    data = request.get_json()
    ZAICO_TOKEN = data.get('token')
    return jsonify({'status': 'success'})

@app.route('/check_inventory', methods=['POST'])
def check_inventory():
    """PDFアップロードで在庫確認"""
    if 'pdf_file' not in request.files:
        return jsonify({'error': 'PDFファイルがありません'}), 400
    
    pdf_file = request.files['pdf_file']
    
    if pdf_file.filename == '':
        return jsonify({'error': 'ファイルが選択されていません'}), 400
    
    # PDFから品番と数量を抽出
    items = extract_hinban_from_pdf(pdf_file)
    
    if not items:
        return jsonify({'error': 'PDFから品番を抽出できませんでした'}), 400
    
    # 在庫データを取得
    all_inventory, error = get_all_inventory_data()
    
    if error:
        return jsonify({'error': error}), 500
    
    # 在庫確認
    results = []
    for item in items:
        hinban = item['hinban']
        required_qty = item['quantity']
        
        # 品番で検索
        stock_item = None
        for inv_item in all_inventory:
            item_code = get_item_code(inv_item)
            if item_code == hinban:
                stock_item = inv_item
                break
        
        if stock_item:
            stock_qty = float(stock_item.get('quantity', 0))
            shortage = max(0, required_qty - stock_qty)
            
            results.append({
                'hinban': hinban,
                'title': stock_item.get('title', ''),
                'required': required_qty,
                'stock': stock_qty,
                'unit': stock_item.get('unit', ''),
                'shortage': shortage,
                'updated_at': stock_item.get('updated_at', ''),
                'status': 'OK' if shortage == 0 else 'NG',
                'category': get_category_from_code(hinban)
            })
        else:
            results.append({
                'hinban': hinban,
                'title': '',
                'required': required_qty,
                'stock': 0,
                'unit': '',
                'shortage': required_qty,
                'updated_at': '',
                'status': 'NOT_FOUND',
                'category': None
            })
    
    return jsonify({'results': results})

@app.route('/check_manual_inventory', methods=['POST'])
def check_manual_inventory():
    """手動入力で在庫確認"""
    data = request.get_json()
    items = data.get('items', [])
    
    if not items:
        return jsonify({'error': '品番がありません'}), 400
    
    # 在庫データを取得
    all_inventory, error = get_all_inventory_data()
    
    if error:
        return jsonify({'error': error}), 500
    
    # 在庫確認
    results = []
    for item in items:
        hinban = item['hinban']
        required_qty = item['quantity']
        
        # 品番で検索
        stock_item = None
        for inv_item in all_inventory:
            item_code = get_item_code(inv_item)
            if item_code == hinban:
                stock_item = inv_item
                break
        
        if stock_item:
            stock_qty = float(stock_item.get('quantity', 0))
            shortage = max(0, required_qty - stock_qty)
            
            results.append({
                'hinban': hinban,
                'title': stock_item.get('title', ''),
                'required': required_qty,
                'stock': stock_qty,
                'unit': stock_item.get('unit', ''),
                'shortage': shortage,
                'updated_at': stock_item.get('updated_at', ''),
                'status': 'OK' if shortage == 0 else 'NG',
                'category': get_category_from_code(hinban)
            })
        else:
            results.append({
                'hinban': hinban,
                'title': '',
                'required': required_qty,
                'stock': 0,
                'unit': '',
                'shortage': required_qty,
                'updated_at': '',
                'status': 'NOT_FOUND',
                'category': None
            })
    
    return jsonify({'results': results})

@app.route('/get_related_parts', methods=['POST'])
def get_related_parts():
    """関連部品を検索 (サイズ表記なし部品も含む)"""
    data = request.get_json()
    product_code = data.get('product_code')
    
    if not product_code:
        return jsonify({'error': '品番がありません'}), 400
    
    category = get_category_from_code(product_code)
    
    if not category:
        return jsonify({'error': '分類コードを取得できません'}), 400
    
    # 在庫データを取得
    all_inventory, error = get_all_inventory_data()
    
    if error:
        return jsonify({'error': error}), 500
    
    # 製品情報
    product_item = None
    for item in all_inventory:
        item_code = get_item_code(item)
        if item_code == product_code:
            product_item = item
            break
    
    if not product_item:
        return jsonify({'error': '製品が見つかりません'}), 404
    
    product_name = product_item.get('title', '')
    product_sizes = extract_sizes_from_name(product_name)
    
    # 関連部品を検索
    related_parts = []
    
    for item in all_inventory:
        item_code = get_item_code(item)
        
        # 同じ分類コードか?
        if not item_code or not item_code.startswith(category):
            continue
        
        item_name = item.get('title', '')
        item_quantity = float(item.get('quantity', 0))
        
        # サイズ表記の有無
        has_size = has_size_notation(item_name)
        
        # サイズ表記なし = 共通部品 (全サイズで使える)
        if not has_size:
            related_parts.append({
                'item_code': item_code,
                'title': item_name,
                'quantity': item_quantity,
                'unit': item.get('unit', ''),
                'updated_at': item.get('updated_at', ''),
                'is_common': True,
                'has_stock': item_quantity > 0,
                'sizes': []
            })
            continue
        
        # サイズ表記あり = サイズ一致をチェック
        item_sizes = extract_sizes_from_name(item_name)
        
        if any(size in product_sizes for size in item_sizes):
            related_parts.append({
                'item_code': item_code,
                'title': item_name,
                'quantity': item_quantity,
                'unit': item.get('unit', ''),
                'updated_at': item.get('updated_at', ''),
                'is_common': False,
                'has_stock': item_quantity > 0,
                'sizes': item_sizes
            })
    
    # ソート: 在庫不足 → 共通部品 → サイズ指定部品
    related_parts.sort(key=lambda x: (
        x['has_stock'],
        not x['is_common'],
        x['item_code']
    ))
    
    # 在庫状況で分類
    shortage_parts = [p for p in related_parts if not p['has_stock']]
    in_stock_parts = [p for p in related_parts if p['has_stock']]
    
    return jsonify({
        'product_code': product_code,
        'product_name': product_name,
        'category_code': category,
        'sizes_found': product_sizes,
        'shortage_count': len(shortage_parts),
        'related_parts': related_parts,
        'shortage_parts': shortage_parts,
        'in_stock_parts': in_stock_parts
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
