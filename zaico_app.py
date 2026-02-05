# Zaico Inventory Check App - Option A (PDF + Manual Input)
# Updated: 2026-02-05
# Feature: PDF受注伝票アップロード + 手動入力 + 関連部品検索（サイズなし共通部品対応）

from flask import Flask, render_template, request, jsonify
import requests
import re
import os
import io
from collections import defaultdict

app = Flask(__name__)

# Zaico API設定
ZAICO_API_URL = 'https://web.zaico.co.jp/api/v1/inventories'
ZAICO_TOKEN = os.environ.get('ZAICO_TOKEN', None)  # 環境変数またはユーザー入力

# サイズパターン（mm表記）
SIZE_PATTERNS = [
    r'(\d+)\s*mm',
    r'(\d+)MM',
    r'φ\s*(\d+)',
    r'(\d+)\s*A',
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
    for pattern in SIZE_PATTERNS:
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

def get_all_inventory_data():
    """全在庫データを取得"""
    if not ZAICO_TOKEN:
        return None, 'トークンが設定されていません'
    
    headers = {
        'Authorization': f'Bearer {ZAICO_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    try:
        response = requests.get(ZAICO_API_URL, headers=headers, params={'per_page': 1000})
        response.raise_for_status()
        data = response.json()
        return data.get('inventories', []), None
    except requests.exceptions.RequestException as e:
        return None, str(e)

def extract_hinban_from_pdf(pdf_file):
    """PDFから品番を抽出（簡易版 - 実際はPDF解析ライブラリが必要）"""
    # 注意: この関数は簡易実装です
    # 本番環境では PyPDF2 や pdfplumber などを使用してください
    
    # 仮実装: PDFファイル名から品番を推測
    # 例: "order_0215-21-13.pdf" -> "0215-21-13"
    filename = pdf_file.filename
    
    # 品番パターンを検索 (XXXX-XX-XX 形式)
    pattern = r'\d{4}-\d{2}-\d{2,4}'
    matches = re.findall(pattern, filename)
    
    if matches:
        # 品番と数量のリストを返す（数量は1と仮定）
        return [{'hinban': match, 'quantity': 1} for match in matches]
    
    # PDFの内容から抽出する場合は以下を使用
    # try:
    #     import PyPDF2
    #     pdf_reader = PyPDF2.PdfReader(pdf_file)
    #     text = ""
    #     for page in pdf_reader.pages:
    #         text += page.extract_text()
    #     matches = re.findall(pattern, text)
    #     return [{'hinban': match, 'quantity': 1} for match in matches]
    # except:
    #     pass
    
    return []

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
    """在庫確認（PDFアップロード対応）"""
    if not ZAICO_TOKEN:
        return jsonify({'error': 'トークンが設定されていません'}), 401
    
    # PDFファイルがアップロードされている場合
    if 'pdf_file' in request.files:
        pdf_file = request.files['pdf_file']
        
        if pdf_file.filename == '':
            return jsonify({'error': 'ファイルが選択されていません'}), 400
        
        # PDFから品番を抽出
        items = extract_hinban_from_pdf(pdf_file)
        
        if not items:
            return jsonify({'error': 'PDFから品番を抽出できませんでした'}), 400
        
        # 各品番の在庫を確認
        inventories, error = get_all_inventory_data()
        if error:
            return jsonify({'error': error}), 500
        
        results = []
        for item in items:
            hinban = item['hinban']
            required_qty = item['quantity']
            
            # 在庫データから該当品番を検索
            found = None
            for inv in inventories:
                if inv.get('item_code') == hinban:
                    found = inv
                    break
            
            if found:
                current_qty = found.get('quantity', 0)
                shortage = max(0, required_qty - current_qty)
                status = 'OK' if current_qty >= required_qty else 'NG'
                
                results.append({
                    'hinban': hinban,
                    'name': found.get('title', ''),
                    'required_qty': required_qty,
                    'current_qty': current_qty,
                    'unit': found.get('unit', '個'),
                    'shortage': shortage,
                    'updated_at': found.get('updated_at', ''),
                    'status': status,
                    'category': found.get('category', '')
                })
            else:
                results.append({
                    'hinban': hinban,
                    'name': '登録なし',
                    'required_qty': required_qty,
                    'current_qty': 0,
                    'unit': '-',
                    'shortage': required_qty,
                    'updated_at': '',
                    'status': 'NOT_FOUND',
                    'category': ''
                })
        
        return jsonify({'results': results})
    
    # PDFなしの場合はエラー
    return jsonify({'error': 'PDFファイルをアップロードしてください'}), 400

@app.route('/check_manual_inventory', methods=['POST'])
def check_manual_inventory():
    """在庫確認（手動入力対応）"""
    if not ZAICO_TOKEN:
        return jsonify({'error': 'トークンが設定されていません'}), 401
    
    data = request.json
    items = data.get('items', [])
    
    if not items:
        return jsonify({'error': '品番を入力してください'}), 400
    
    # 全在庫データを取得
    inventories, error = get_all_inventory_data()
    if error:
        return jsonify({'error': error}), 500
    
    results = []
    for item in items:
        hinban = item['hinban']
        required_qty = item['quantity']
        
        # 在庫データから該当品番を検索
        found = None
        for inv in inventories:
            if inv.get('item_code') == hinban:
                found = inv
                break
        
        if found:
            current_qty = found.get('quantity', 0)
            shortage = max(0, required_qty - current_qty)
            status = 'OK' if current_qty >= required_qty else 'NG'
            
            results.append({
                'hinban': hinban,
                'name': found.get('title', ''),
                'required_qty': required_qty,
                'current_qty': current_qty,
                'unit': found.get('unit', '個'),
                'shortage': shortage,
                'updated_at': found.get('updated_at', ''),
                'status': status,
                'category': found.get('category', '')
            })
        else:
            results.append({
                'hinban': hinban,
                'name': '登録なし',
                'required_qty': required_qty,
                'current_qty': 0,
                'unit': '-',
                'shortage': required_qty,
                'updated_at': '',
                'status': 'NOT_FOUND',
                'category': ''
            })
    
    return jsonify({'results': results})

@app.route('/get_related_parts', methods=['POST'])
def get_related_parts():
    """関連部品を取得（サイズなし共通部品も含む）"""
    if not ZAICO_TOKEN:
        return jsonify({'error': 'トークンが設定されていません'}), 401
    
    data = request.json
    category = data.get('category', '').strip()
    shortage = data.get('shortage', 0)
    product_name = data.get('product_name', '')
    
    if not category:
        return jsonify({'error': 'カテゴリを指定してください'}), 400
    
    # 全在庫データを取得
    inventories, error = get_all_inventory_data()
    if error:
        return jsonify({'error': error}), 500
    
    # 製品名からサイズを抽出
    target_sizes = extract_sizes_from_name(product_name)
    
    # 同じカテゴリの部品を検索
    related_parts = []
    
    for item in inventories:
        item_category = item.get('category', '')
        item_code = item.get('item_code', '')
        item_name = item.get('title', '')
        quantity = item.get('quantity', 0)
        unit = item.get('unit', '個')
        updated_at = item.get('updated_at', '')
        
        # カテゴリが一致するか確認
        if category.lower() not in item_category.lower():
            # 品番の最初の4桁で分類コードをチェック
            item_category_code = get_category_from_code(item_code)
            category_code = get_category_from_code(category) if '-' in category else category[:4]
            
            if item_category_code != category_code:
                continue
        
        # サイズ表記の有無を判定
        item_has_size = has_size_notation(item_name)
        
        # サイズ表記なし = 全サイズ共通部品
        is_common_part = not item_has_size
        
        # サイズ表記あり = サイズが一致するか確認
        is_size_match = False
        if item_has_size and target_sizes:
            item_sizes = extract_sizes_from_name(item_name)
            # 製品に必要なサイズと部品のサイズが一致
            is_size_match = any(size in target_sizes for size in item_sizes)
        
        # 共通部品 または サイズ一致の部品を追加
        if is_common_part or is_size_match:
            # 警告判定：在庫数が不足数より少ない場合
            warning = quantity < shortage if shortage > 0 else False
            
            related_parts.append({
                'hinban': item_code,
                'name': item_name,
                'quantity': quantity,
                'unit': unit,
                'updated_at': updated_at,
                'warning': warning,
                'is_common_part': is_common_part,
                'is_size_match': is_size_match,
                'is_shortage': quantity == 0
            })
    
    # ソート：在庫不足 > 共通部品 > サイズ指定部品
    related_parts.sort(key=lambda x: (
        not x['is_shortage'],  # 在庫不足を先に
        not x['is_common_part'],  # 共通部品を次に
        x['hinban']
    ))
    
    return jsonify({
        'category': category,
        'product_name': product_name,
        'target_sizes': target_sizes,
        'shortage': shortage,
        'parts': related_parts
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
