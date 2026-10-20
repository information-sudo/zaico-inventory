import os
from flask import Flask, render_template, request, jsonify
import requests
import pypdf
import re
from io import BytesIO
from datetime import datetime, timedelta

app = Flask(__name__)

# Zaico API設定
ZAICO_API_TOKEN = "jrmXaweTqNZdPN9HCiSF7VGskW2NBCPY"
ZAICO_API_BASE_URL = "https://web.zaico.co.jp/api/v1"

# キャッシュ設定
inventory_cache = {
    'data': [],
    'timestamp': None,
    'ttl': 300  # 5分間有効
}

def extract_items_from_pdf(pdf_file):
    """受注票PDFから品番と数量を抽出"""
    items = []
    
    pdf_reader = pypdf.PdfReader(pdf_file)
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text()
    
    lines = text.split('\n')
    hinban_list = []
    
    for i, line in enumerate(lines):
        # 「購入品」を含む行から品番を抽出
        if '購入品' in line:
            # 「購入品」より後ろの部分を取得
            after_kounyuuhin = line.split('購入品', 1)[1].strip()
            # 品番パターン: xxxx-xx-xx または xxxx-xx-xxx + 明細番号3桁（英字・ハイフン複数対応）
            pattern = r'(\d{4}-\d{2}-[A-Z0-9\-]+?)(\d{3})$'
            matches = re.findall(pattern, after_kounyuuhin)
            
            if matches:
                # 最後のマッチから品番を取得（図面番号がある場合は後ろの方）
                hinban, meisai_no = matches[-1]
                quantity = 1
                if i >= 1:
                    prev_line = lines[i - 1].strip()
                    qty_match = re.match(r'^(\d+)\s+', prev_line)
                    if qty_match:
                        quantity = int(qty_match.group(1))
                hinban_list.append({'hinban': hinban, 'quantity': quantity})
    
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
            match = re.search(r'page=(\d+)&per_page=\d+>; rel="last"', link_header)
            if match:
                return int(match.group(1))
        
        return 10
    except Exception as e:
        print(f"総ページ数取得エラー: {e}")
        return 10

def load_all_inventories():
    """全在庫データを一括取得してキャッシュ"""
    global inventory_cache
    
    # キャッシュが有効かチェック
    if inventory_cache['timestamp']:
        elapsed = datetime.now() - inventory_cache['timestamp']
        if elapsed.total_seconds() < inventory_cache['ttl']:
            print(f"✓ キャッシュを使用（残り有効時間: {int(inventory_cache['ttl'] - elapsed.total_seconds())}秒）")
            return inventory_cache['data']
    
    print("📦 全在庫データを取得中...")
    
    headers = {
        "Authorization": f"Bearer {ZAICO_API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    all_inventories = []
    
    try:
        total_pages = min(get_total_pages(), 100)  # 最大20ページ
        print(f"📄 全 {total_pages} ページを取得します...")
        
        for page in range(1, total_pages + 1):
            print(f"  ページ {page}/{total_pages} 取得中...", end=' ')
            
            response = requests.get(
                f"{ZAICO_API_BASE_URL}/inventories",
                headers=headers,
                params={"page": page, "per_page": 100},
                timeout=15
            )
            
            if response.status_code != 200:
                print(f"❌ 失敗 (status: {response.status_code})")
                continue
            
            data = response.json()
            
            if not data:
                print("⚠ データなし")
                break
            
            all_inventories.extend(data)
            print(f"✓ {len(data)}件")
        
        # キャッシュを更新
        inventory_cache['data'] = all_inventories
        inventory_cache['timestamp'] = datetime.now()
        
        print(f"✅ 合計 {len(all_inventories)} 件の在庫データを取得しました")
        
        return all_inventories
        
    except Exception as e:
        print(f"❌ エラー: {e}")
        return []

def search_zaico_inventory(hinban):
    """キャッシュから品番を検索"""
    print(f"🔍 品番 {hinban} を検索中...")
    
    # 全在庫データを取得（キャッシュから）
    all_inventories = load_all_inventories()
    
    if not all_inventories:
        return {
            'success': False,
            'error': '在庫データの取得に失敗しました'
        }
    
    # キャッシュから検索
    for inventory in all_inventories:
        optional_attrs = inventory.get('optional_attributes', [])
        hinban_value = ''
        
        for attr in optional_attrs:
            if attr.get('name') == '品番':
                hinban_value = attr.get('value', '')
                break
        
        if hinban_value == hinban:
            print(f"  ✓ 品番 {hinban} を発見")
            print(f"    - title: {inventory.get('title', '')}")
            print(f"    - quantity: {inventory.get('quantity', 0)}")
            print(f"    - category: {inventory.get('category', '')}")
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
    
    print(f"  ✗ 品番 {hinban} が見つかりませんでした")
    return {
        'success': False,
        'error': '品番が見つかりませんでした'
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
        
        print(f"品番 {hinban} （必要数: {required_qty}）")
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
                'updated_at': inventory_info.get('updated_at', ''),
                'category': inventory_info.get('category', '')
            })
        else:
            results.append({
                'hinban': hinban,
                'name': 'Zaico未登録',
                'required_qty': required_qty,
                'current_qty': 0,
                'unit': '-',
                'status': 'NOT_FOUND',
                'shortage': required_qty,
                'zaico_code': '',
                'zaico_id': '',
                'updated_at': ''
            })
    
    return results

@app.route('/get_related_parts', methods=['POST'])
def get_related_parts():
    """製品分類が同じ部品・製品を取得（サイズフィルタリング付き）"""
    data = request.get_json()
    category = data.get('category', '').strip()
    shortage = data.get('shortage', 0)
    product_name = data.get('product_name', '').strip()
    
    if not category:
        return jsonify({'error': '製品分類が指定されていません'}), 400
    
    print(f"\n=== 製品分類 {category} の関連部品を検索 ===")
    print(f"  不足製品: {product_name}")
    
    # 不足品からサイズを抽出
    target_sizes = extract_sizes(product_name)
    print(f"  抽出されたサイズ: {list(target_sizes)}")
    
    # 全在庫データから同じ製品分類を検索
    all_inventories = load_all_inventories()
    
    related_parts = []
    for inventory in all_inventories:
        if inventory.get('category', '') == category:
            inventory_name = inventory.get('title', '')
            
            # サイズフィルタリング（無効化）
            # if target_sizes:
            #     inventory_sizes = extract_sizes(inventory_name)
            #     if not inventory_sizes:
            #         continue  # サイズがない場合は除外
            #     if not sizes_match(target_sizes, inventory_sizes):
            #         continue  # サイズが一致しない
            
            quantity = float(inventory.get('quantity', 0) or 0)
            
            # 警告判定: 不足数より在庫が少ない
            warning = quantity < shortage if shortage > 0 else False
            
            # 品番を取得
            optional_attrs = inventory.get('optional_attributes', [])
            hinban_value = ''
            for attr in optional_attrs:
                if attr.get('name') == '品番':
                    hinban_value = attr.get('value', '')
                    break
            
            related_parts.append({
                'hinban': hinban_value,
                'name': inventory_name,
                'quantity': quantity,
                'unit': inventory.get('unit', '個'),
                'zaico_code': inventory.get('code', ''),
                'updated_at': inventory.get('updated_at', ''),
                'warning': warning
            })
    
    print(f"  ✓ {len(related_parts)} 件の関連部品を発見（サイズフィルタ適用後）")
    
    return jsonify({
        'category': category,
        'shortage': shortage,
        'product_name': product_name,
        'target_sizes': list(target_sizes),  # setをlistに変換
        'parts': related_parts
    })

def extract_sizes(text):
    """品名からサイズを抽出（mm, A, インチ）"""
    sizes = set()
    
    # mmサイズ: 10mm, 13mm, 16mm, 20mm, 25mm, 32mm etc.
    mm_matches = re.findall(r'(\d+)\s*mm', text, re.IGNORECASE)
    for m in mm_matches:
        sizes.add(int(m))
    
    # Aサイズ: 10A, 13A, 16A, 20A, 25A, 32A etc.
    a_matches = re.findall(r'(\d+)\s*A(?![a-zA-Z])', text)
    for m in a_matches:
        sizes.add(int(m))
    
    # インチサイズをmmに変換
    inch_map = {
        '3/8': 10,
        '1/2': 13,
        '5/8': 16,
        '3/4': 20,
        '1': 25,
        '1 1/4': 32,
        '1 1/2': 40,
        '2': 50
    }
    
    for inch_str, mm_size in inch_map.items():
        # インチ表記を検索: ( 1/2 ), (1/2), 1/2
        if f'({inch_str})' in text or f'( {inch_str} )' in text or f' {inch_str} ' in text:
            sizes.add(mm_size)
    
    return sizes

def sizes_match(sizes1, sizes2):
    """サイズが一致するか判定"""
    return bool(sizes1 & sizes2)  # 交差があればTrue

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
