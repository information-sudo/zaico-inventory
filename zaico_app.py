# Zaico Inventory Check App - Fixed Version
# Updated: 2026-02-05
# Feature: サイズなし部品（全サイズ共通部品）も関連部品リストに表示

from flask import Flask, render_template, request, jsonify
import requests
import re
from collections import defaultdict

app = Flask(__name__)

# Zaico API設定
ZAICO_API_URL = 'https://web.zaico.co.jp/api/v1/inventories'
ZAICO_TOKEN = None  # 環境変数から取得するか、ユーザーが入力

# サイズパターン（mm表記）
SIZE_PATTERNS = [
    r'(\d+)\s*mm',
    r'(\d+)MM',
    r'φ\s*(\d+)',
    r'(\d+)\s*A',
    r'1/2',  # 13mm相当
    r'3/8',  # 10mm相当
    r'5/8',  # 16mm相当
    r'3/4',  # 20mm相当
    r'1',    # 25mm相当
]

# インチ→mm変換テーブル
INCH_TO_MM = {
    '1/2': 13,
    '3/8': 10,
    '5/8': 16,
    '3/4': 20,
    '1': 25,
}

def extract_sizes_from_name(item_name):
    """物品名からサイズを抽出"""
    sizes = set()
    item_name_lower = item_name.lower()
    
    # インチ表記の検索
    for inch_str, mm_val in INCH_TO_MM.items():
        if inch_str in item_name_lower:
            sizes.add(mm_val)
    
    # mm表記の検索
    for pattern in SIZE_PATTERNS[:4]:  # mm系のパターンのみ
        matches = re.findall(pattern, item_name_lower)
        for match in matches:
            try:
                sizes.add(int(match))
            except:
                pass
    
    return list(sizes)

def has_size_notation(item_name):
    """サイズ表記があるかチェック"""
    sizes = extract_sizes_from_name(item_name)
    return len(sizes) > 0

def get_category_from_code(item_code):
    """品番から分類コードを取得（最初の4桁）"""
    if not item_code:
        return None
    
    # ハイフンで分割して最初の部分を取得
    parts = item_code.split('-')
    if len(parts) > 0:
        return parts[0][:4]  # 最初の4桁
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/set_token', methods=['POST'])
def set_token():
    """Zaicoトークンを設定"""
    global ZAICO_TOKEN
    data = request.json
    ZAICO_TOKEN = data.get('token')
    return jsonify({'success': True})

@app.route('/check_inventory', methods=['POST'])
def check_inventory():
    """在庫確認"""
    if not ZAICO_TOKEN:
        return jsonify({'error': 'トークンが設定されていません'}), 401
    
    headers = {
        'Authorization': f'Bearer {ZAICO_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    try:
        # 全在庫データを取得
        response = requests.get(ZAICO_API_URL, headers=headers, params={'per_page': 1000})
        response.raise_for_status()
        
        data = response.json()
        inventories = data.get('inventories', [])
        
        # 在庫あり/なしで分類
        in_stock = []
        out_of_stock = []
        
        for item in inventories:
            item_code = item.get('item_code', '')
            title = item.get('title', '')
            quantity = item.get('quantity', 0)
            category = item.get('category', '')
            
            item_info = {
                'item_code': item_code,
                'title': title,
                'quantity': quantity,
                'category': category
            }
            
            if quantity > 0:
                in_stock.append(item_info)
            else:
                out_of_stock.append(item_info)
        
        return jsonify({
            'total': len(inventories),
            'in_stock_count': len(in_stock),
            'out_of_stock_count': len(out_of_stock),
            'in_stock': in_stock,
            'out_of_stock': out_of_stock
        })
        
    except requests.exceptions.RequestException as e:
        return jsonify({'error': str(e)}), 500

@app.route('/search_item', methods=['POST'])
def search_item():
    """品番で在庫検索"""
    if not ZAICO_TOKEN:
        return jsonify({'error': 'トークンが設定されていません'}), 401
    
    data = request.json
    search_code = data.get('item_code', '').strip()
    
    if not search_code:
        return jsonify({'error': '品番を入力してください'}), 400
    
    headers = {
        'Authorization': f'Bearer {ZAICO_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    try:
        # 全在庫データを取得
        response = requests.get(ZAICO_API_URL, headers=headers, params={'per_page': 1000})
        response.raise_for_status()
        
        data = response.json()
        inventories = data.get('inventories', [])
        
        # 品番で検索
        found_items = []
        for item in inventories:
            item_code = item.get('item_code', '')
            if search_code.lower() in item_code.lower():
                found_items.append({
                    'item_code': item_code,
                    'title': item.get('title', ''),
                    'quantity': item.get('quantity', 0),
                    'category': item.get('category', '')
                })
        
        if found_items:
            return jsonify({
                'success': True,
                'items': found_items
            })
        else:
            return jsonify({
                'success': False,
                'message': f'品番「{search_code}」に該当する製品が見つかりませんでした'
            })
        
    except requests.exceptions.RequestException as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_related_parts', methods=['POST'])
def get_related_parts():
    """関連部品を取得（サイズなし共通部品も含む）"""
    if not ZAICO_TOKEN:
        return jsonify({'error': 'トークンが設定されていません'}), 401
    
    data = request.json
    product_code = data.get('product_code', '').strip()
    
    if not product_code:
        return jsonify({'error': '製品品番を入力してください'}), 400
    
    headers = {
        'Authorization': f'Bearer {ZAICO_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    try:
        # 全在庫データを取得
        response = requests.get(ZAICO_API_URL, headers=headers, params={'per_page': 1000})
        response.raise_for_status()
        
        inventory_data = response.json()
        inventories = inventory_data.get('inventories', [])
        
        # 製品情報を検索
        product_info = None
        for item in inventories:
            if item.get('item_code', '') == product_code:
                product_info = item
                break
        
        if not product_info:
            return jsonify({
                'success': False,
                'message': f'製品品番「{product_code}」が見つかりませんでした'
            })
        
        product_name = product_info.get('title', '')
        product_category_code = get_category_from_code(product_code)
        
        if not product_category_code:
            return jsonify({
                'success': False,
                'message': '製品の分類コードを取得できませんでした'
            })
        
        # 製品に必要なサイズを抽出
        required_sizes = extract_sizes_from_name(product_name)
        
        # 関連部品を検索（同じ分類コードの部品）
        related_parts = []
        
        for item in inventories:
            item_code = item.get('item_code', '')
            item_name = item.get('title', '')
            quantity = item.get('quantity', 0)
            category = item.get('category', '')
            
            # 分類コードを取得
            item_category_code = get_category_from_code(item_code)
            
            # 同じ分類コードの部品のみ対象
            if item_category_code != product_category_code:
                continue
            
            # 製品自身は除外
            if item_code == product_code:
                continue
            
            # サイズ表記の有無を判定
            item_has_size = has_size_notation(item_name)
            
            # サイズ表記なし = 全サイズ共通部品
            is_common_part = not item_has_size
            
            # サイズ表記あり = サイズが一致するか確認
            is_size_match = False
            if item_has_size and required_sizes:
                item_sizes = extract_sizes_from_name(item_name)
                # 製品に必要なサイズと部品のサイズが一致
                is_size_match = any(size in required_sizes for size in item_sizes)
            
            # 共通部品 または サイズ一致の部品を追加
            if is_common_part or is_size_match:
                related_parts.append({
                    'item_code': item_code,
                    'title': item_name,
                    'quantity': quantity,
                    'category': category,
                    'is_shortage': quantity == 0,
                    'is_common_part': is_common_part,
                    'is_size_match': is_size_match
                })
        
        # ソート：在庫不足 > 共通部品 > サイズ指定部品
        related_parts.sort(key=lambda x: (
            not x['is_shortage'],  # 在庫不足を先に
            not x['is_common_part'],  # 共通部品を次に
            x['item_code']
        ))
        
        # 在庫不足の部品を抽出
        shortage_parts = [p for p in related_parts if p['is_shortage']]
        
        return jsonify({
            'success': True,
            'product_code': product_code,
            'product_name': product_name,
            'category_code': product_category_code,
            'sizes_found': required_sizes,  # listに変換済み
            'shortage_count': len(shortage_parts),
            'related_parts': related_parts,
            'shortage_parts': shortage_parts
        })
        
    except requests.exceptions.RequestException as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
