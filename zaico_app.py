import os
from flask import Flask, render_template, request, jsonify
import requests
import PyPDF2
import re
from io import BytesIO

app = Flask(__name__)

# Zaico API設定
ZAICO_API_TOKEN = "jrmXaweTqNZdPN9HCiSF7VGskW2NBCPY"
ZAICO_API_BASE_URL = "https://web.zaico.co.jp/api/v1"

def extract_items_from_pdf(pdf_file):
    """受注票PDFから品番と数量を抽出（固定書式対応）"""
    items = []
    
    pdf_reader = PyPDF2.PdfReader(pdf_file)
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text()
    
    lines = text.split('\n')
    
    hinban_list = []
    
    for i, line in enumerate(lines):
        # 品番パターン: 購入品 の後に続く品番（例: 0215-21-10001）
        hinban_match = re.search(r'購入品\s+(\d{4}-\d{2}-[A-Z0-9\-]+?)(\d{3})\s*$', line)
        if hinban_match:
            hinban = hinban_match.group(1)  # 末尾3桁（明細番号）を除いた品番
            
            # 1行前を確認（受注数量が入っている）
            # パターン: "10 式 17,500..." → 先頭の数字が受注数量
            quantity = 1  # デフォルト
            if i >= 1:
                prev_line = lines[i - 1].strip()
                # 行の先頭が数字で始まる場合
                qty_match = re.match(r'^(\d+)\s+', prev_line)
                if qty_match:
                    quantity = int(qty_match.group(1))
            
            hinban_list.append({
                'hinban': hinban,
                'quantity': quantity
            })
    
    # 重複を除去
    seen = set()
    unique_items = []
    for item in hinban_list:
        key = item['hinban']
        if key not in seen:
            seen.add(key)
            unique_items.append(item)
    
    return unique_items

def get_total_pages():
    """Link Headerから総ページ数を取得"""
    headers = {
        "Authorization": f"Bearer {ZAICO_API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(
            f"{ZAICO_API_BASE_URL}/inventories",
            headers=headers,
            params={"page": 1, "per_page": 100},
            timeout=10
        )
        
        if response.status_code == 200:
            link_header = response.headers.get('Link', '')
            # rel="last"の直前のpage番号を抽出（per_pageを除外）
            match = re.search(r'page=(\d+)&per_page=\d+>; rel="last"', link_header)
            if match:
                return int(match.group(1))
        
        return 10  # デフォルト10ページ
    except Exception as e:
        print(f"総ページ数取得エラー: {e}")
        return 10

def search_zaico_inventory(hinban):
    """全ページを検索して品番を探す（optional_attributes対応）"""
    headers = {
        "Authorization": f"Bearer {ZAICO_API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        total_pages = get_total_pages()
        
        for page in range(1, total_pages + 1):
            response = requests.get(
                f"{ZAICO_API_BASE_URL}/inventories",
                headers=headers,
                params={"page": page, "per_page": 100},
                timeout=10
            )
            
            if response.status_code != 200:
                continue
            
            data = response.json()
            
            if not data:
                break
            
            # 各データを検索
            for inventory in data:
                # optional_attributesから品番を検索
                optional_attrs = inventory.get('optional_attributes', [])
                hinban_value = ''
                
                for attr in optional_attrs:
                    if attr.get('name') == '品番':
                        hinban_value = attr.get('value', '')
                        break
                
                # 品番が一致するかチェック
                if hinban_value == hinban:
                    return {
                        'success': True,
                        'hinban': hinban_value,
                        'name': inventory.get('title', ''),
                        'quantity': float(inventory.get('quantity', 0) or 0),
                        'unit': inventory.get('unit', '個'),
                        'zaico_code': inventory.get('code', ''),
                        'zaico_id': inventory.get('id', ''),
                        'category': inventory.get('category', ''),
                        'updated_at': inventory.get('updated_at', '')
                    }
        
        return {
            'success': False,
            'error': '品番が見つかりませんでした'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'通信エラー: {str(e)}'
        }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/test')
def test():
    return render_template('test.html')

@app.route('/check_hinban', methods=['POST'])
def check_hinban():
    data = request.get_json()
    hinban = data.get('hinban', '').strip()
    
    if not hinban:
        return jsonify({'success': False, 'error': '品番を入力してください'}), 400
    
    print(f"\n=== 品番検索: {hinban} ===")
    result = search_zaico_inventory(hinban)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 404

@app.route('/check_inventory', methods=['POST'])
def check_inventory():
    if 'pdf_file' not in request.files:
        return jsonify({'error': 'PDFファイルがアップロードされていません'}), 400
    
    pdf_file = request.files['pdf_file']
    
    if pdf_file.filename == '':
        return jsonify({'error': 'ファイルが選択されていません'}), 400
    
    if not pdf_file.filename.endswith('.pdf'):
        return jsonify({'error': 'PDFファイルをアップロードしてください'}), 400
    
    try:
        # PDFから品番と数量を抽出
        items = extract_items_from_pdf(BytesIO(pdf_file.read()))
        
        if not items:
            return jsonify({'error': 'PDFから品番を抽出できませんでした'}), 400
        
        print(f"\n=== 受注伝票から{len(items)}件の品番を抽出 ===")
        for item in items:
            print(f"  品番: {item['hinban']}, 数量: {item['quantity']}")
        
        results = check_items_inventory(items)
        
        print(f"=== 在庫確認完了 ===\n")
        return jsonify({'results': results})
    
    except Exception as e:
        return jsonify({'error': f'処理中にエラーが発生しました: {str(e)}'}), 500

@app.route('/check_manual_inventory', methods=['POST'])
def check_manual_inventory():
    data = request.get_json()
    items = data.get('items', [])
    
    if not items:
        return jsonify({'error': '品番が入力されていません'}), 400
    
    try:
        print(f"\n=== 手動入力から{len(items)}件の品番を確認 ===")
        results = check_items_inventory(items)
        
        print(f"=== 在庫確認完了 ===\n")
        return jsonify({'results': results})
    
    except Exception as e:
        return jsonify({'error': f'処理中にエラーが発生しました: {str(e)}'}), 500

def check_items_inventory(items):
    """品番リストの在庫を確認"""
    results = []
    for item in items:
        hinban = item['hinban']
        required_qty = item['quantity']
        
        print(f"品番 {hinban} （必要数: {required_qty}）を検索中...")
        inventory_info = search_zaico_inventory(hinban)
        
        if inventory_info['success']:
            current_qty = inventory_info['quantity']
            status = 'OK' if current_qty >= required_qty else 'NG'
            
            results.append({
                'hinban': hinban,
                'name': inventory_info['name'],
                'required_qty': required_qty,
                'current_qty': current_qty,
                'unit': inventory_info['unit'],
                'status': status,
                'shortage': max(0, required_qty - current_qty),
                'zaico_code': inventory_info.get('zaico_code', ''),
                'zaico_id': inventory_info.get('zaico_id', ''),
                'updated_at': inventory_info.get('updated_at', '')
            })
        else:
            results.append({
                'hinban': hinban,
                'name': '-',
                'required_qty': required_qty,
                'current_qty': 0,
                'unit': '個',
                'status': 'ERROR',
                'error': inventory_info['error']
            })
    
    return results

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
