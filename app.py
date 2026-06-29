import os
import json
import time
from flask import Flask, request, jsonify, send_from_directory
from PIL import Image, ImageDraw, ImageOps  # ImageOps 负责自动读取并物理扶正 iPhone 旋转

app = Flask(__name__)

# 🔒 绝对路径锁定：确保任何环境下运行都不会迷路
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'coins_data.json')
IMAGE_DIR = os.path.join(BASE_DIR, 'images')

# 自动建立图片存放文件夹
if not os.path.exists(IMAGE_DIR):
    os.makedirs(IMAGE_DIR)

# =====================================================================
# 核心算法：完美逆向映射前端 CSS object-fit: cover 视界，做到像素级无偏差
# =====================================================================
def crop_coin_to_circle(source_path, target_path, rot_deg, cx_pct, cy_pct, r_pct):
    try:
        if not os.path.exists(source_path):
            return
        
        with Image.open(source_path) as img:
            # 🌟 1. 自动读取并应用 Exif 旋转标记，彻底扶正躺着的 iPhone 画面像素！
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGBA")
            
            # 🌟 2. 智能等比例降采样（限制最大单边 1200 像素，平衡运算速度与清晰度）
            max_size = 1200
            if img.width > max_size or img.height > max_size:
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            
            # 🌟 3. 如果用户在前端指定了旋转角度，先对原图做平滑旋转
            if abs(rot_deg) > 0.01:
                img = img.rotate(-rot_deg, resample=Image.Resampling.BICUBIC, expand=False)
            
            w_img, h_img = img.size
            
            # 🎯 4. 绝杀核心数学修正：完美逆向推导前端 CSS 的 object-fit: cover 视界
            # 前端预览框是一个 1:1 的正方形框。长方形图片缩放后，短边充满正方形，长边溢出并被正方形两侧/上下裁剪。
            if w_img > h_img:
                # 宽图：高度充满正方形框（即大图 h_img 对应前端正方形框的 100% 视界）
                box_pixel_size = h_img
                # 计算因为居中显示（cover）导致大图左侧被裁剪掉的像素偏移量
                x_offset = (w_img - h_img) / 2.0
                y_offset = 0.0
            else:
                # 长/高图：宽度充满正方形框（即大图 w_img 对应前端正方形框的 100% 视界）
                box_pixel_size = w_img
                x_offset = 0.0
                # 计算因为居中显示（cover）导致大图顶部被裁剪掉的像素偏移量
                y_offset = (h_img - w_img) / 2.0

            # 🎯 5. 将基于前端正方形框的百分比，精准换算为大图上真实的绝对物理像素坐标
            cx = x_offset + (float(cx_pct) / 100.0) * box_pixel_size
            cy = y_offset + (float(cy_pct) / 100.0) * box_pixel_size
            r = (float(r_pct) / 100.0) * box_pixel_size
            
            # 6. 安全物理边界检测与容错
            left = max(0, int(round(cx - r)))
            top = max(0, int(round(cy - r)))
            right = min(w_img, int(round(cx + r)))
            bottom = min(h_img, int(round(cy + r)))
            
            # 7. 创建同等大小的纯黑透明遮罩画布
            mask = Image.new("L", img.size, 0)
            draw = ImageDraw.Draw(mask)
            # 在遮罩层绘制高精度白色纯圆（255 代表保留区域）
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
            
            # 8. 像素融合：注入透明通道
            output = Image.new("RGBA", img.size, (0, 0, 0, 0))
            output.paste(img, (0, 0), mask=mask)
            
            # 9. 裁剪提取紧凑的纯圆外接正方形，消除外部多余的透明死区留白
            cropped_output = output.crop((left, top, right, bottom))
            
            # 保存为透明 PNG 格式
            cropped_output.save(target_path, "PNG")
            print(f"🎯 CSS视界完美对齐！圆形硬币已成功物理套圈导出至: {target_path}")
            
    except Exception as e:
        print(f"❌ 圆形抠图算法发生严重崩溃: {str(e)}")

# =====================================================================
# 页面及静态资源路由网关区
# =====================================================================

# 大厅首页
@app.route('/')
def index_page():
    return send_from_directory(BASE_DIR, 'index.html')

# 🎯 核心兼容路由：前端不改、继续请求 'admin.html'，后端也提供完美兼容别名，无缝识别放行！
@app.route('/admin')
@app.route('/admin.html')
def admin_page():
    return send_from_directory(BASE_DIR, 'admin.html')

# 物理磁盘图片文件访问支持
@app.route('/images/<filename>')
def serve_image(filename):
    return send_from_directory(IMAGE_DIR, filename)

# =====================================================================
# 藏品账本 API 数据交换区
# =====================================================================

# 1. 获取账本列表
@app.route('/api/coins', methods=['GET'])
def get_coins():
    if not os.path.exists(DATA_FILE):
        return jsonify([])
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify([])

# 2. 写入或编辑藏品（支持大图接收、多张细节图追加及圆形切块）
@app.route('/api/coins', methods=['POST'])
def save_coin():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                coins = json.load(f)
        else:
            coins = []

        idx = int(request.form.get('edit_index', -1))
        
        # 处理并生成新数据结构
        coin_entry = {
            "name": request.form.get('name', '').strip(),
            "price": request.form.get('price', '0'),
            "currency": request.form.get('currency', 'CNY'),
            "platform": request.form.get('platform', '').strip(),
            "size": request.form.get('size', '').strip(),
            "notes": request.form.get('notes', '').strip(),
            "date": time.strftime("%Y-%m-%d"),
            "angle_obv": float(request.form.get('angle_obv', 0)),
            "angle_rev": float(request.form.get('angle_rev', 0)),
            "angle_edge": float(request.form.get('angle_edge', 0)),
            "obv_crop_x": float(request.form.get('obv_crop_x', 50)),
            "obv_crop_y": float(request.form.get('obv_crop_y', 50)),
            "obv_crop_r": float(request.form.get('obv_crop_r', 42)),
            "rev_crop_x": float(request.form.get('rev_crop_x', 50)),
            "rev_crop_y": float(request.form.get('rev_crop_y', 50)),
            "rev_crop_r": float(request.form.get('rev_crop_r', 42)),
            "obverse_img": "",
            "reverse_img": "",
            "edge_img": "",
            "obverse_raw_path": "",
            "reverse_raw_path": "",
            "extra_imgs": []
        }

        # 如果是编辑模式，预先拉取旧数据进行覆盖保护
        if idx != -1 and 0 <= idx < len(coins):
            old_coin = coins[idx]
            coin_entry['date'] = old_coin.get('date', coin_entry['date'])
            coin_entry['obverse_img'] = old_coin.get('obverse_img', '')
            coin_entry['reverse_img'] = old_coin.get('reverse_img', '')
            coin_entry['edge_img'] = old_coin.get('edge_img', '')
            coin_entry['obverse_raw_path'] = old_coin.get('obverse_raw_path', '')
            coin_entry['reverse_raw_path'] = old_coin.get('reverse_raw_path', '')
            
            # 获取前端传回需要保持的存量细节图片列表
            keep_extra_str = request.form.get('keep_extra_imgs', '[]')
            coin_entry['extra_imgs'] = json.loads(keep_extra_str)

        # 检查图片清除状态标记
        if request.form.get('obv_cleared') == 'true':
            coin_entry['obverse_img'] = ""; coin_entry['obverse_raw_path'] = ""
        if request.form.get('rev_cleared') == 'true':
            coin_entry['reverse_img'] = ""; coin_entry['reverse_raw_path'] = ""
        if request.form.get('edge_cleared') == 'true':
            coin_entry['edge_img'] = ""

        timestamp = int(time.time())
        
        # 📌 A. 处理并秒抠【正面】大图
        file_obv = request.files.get('obverse_img')
        if file_obv:
            raw_name = f"obv_raw_{timestamp}_{file_obv.filename}"
            raw_path = os.path.join(IMAGE_DIR, raw_name)
            file_obv.save(raw_path)
            coin_entry['obverse_raw_path'] = f"/images/{raw_name}"
            
            cut_name = f"obv_cut_{timestamp}.png"
            cut_path = os.path.join(IMAGE_DIR, cut_name)
            crop_coin_to_circle(raw_path, cut_path, coin_entry['angle_obv'], coin_entry['obv_crop_x'], coin_entry['obv_crop_y'], coin_entry['obv_crop_r'])
            coin_entry['obverse_img'] = f"/images/{cut_name}"
        elif request.form.get('obv_crop_active') == 'true' and coin_entry['obverse_raw_path']:
            # 无新图上传，但微调了圆心半径参数时，基于历史原图重新圆形套圈
            raw_name = os.path.basename(coin_entry['obverse_raw_path'])
            raw_path = os.path.join(IMAGE_DIR, raw_name)
            cut_name = f"obv_cut_{timestamp}.png"
            cut_path = os.path.join(IMAGE_DIR, cut_name)
            crop_coin_to_circle(raw_path, cut_path, coin_entry['angle_obv'], coin_entry['obv_crop_x'], coin_entry['obv_crop_y'], coin_entry['obv_crop_r'])
            coin_entry['obverse_img'] = f"/images/{cut_name}"

        # 📌 B. 处理并秒抠【反面】大图
        file_rev = request.files.get('reverse_img')
        if file_rev:
            raw_name = f"rev_raw_{timestamp}_{file_rev.filename}"
            raw_path = os.path.join(IMAGE_DIR, raw_name)
            file_rev.save(raw_path)
            coin_entry['reverse_raw_path'] = f"/images/{raw_name}"
            
            cut_name = f"rev_cut_{timestamp}.png"
            cut_path = os.path.join(IMAGE_DIR, cut_name)
            crop_coin_to_circle(raw_path, cut_path, coin_entry['angle_rev'], coin_entry['rev_crop_x'], coin_entry['rev_crop_y'], coin_entry['rev_crop_r'])
            coin_entry['reverse_img'] = f"/images/{cut_name}"
        elif request.form.get('rev_crop_active') == 'true' and coin_entry['reverse_raw_path']:
            raw_name = os.path.basename(coin_entry['reverse_raw_path'])
            raw_path = os.path.join(IMAGE_DIR, raw_name)
            cut_name = f"rev_cut_{timestamp}.png"
            cut_path = os.path.join(IMAGE_DIR, cut_name)
            crop_coin_to_circle(raw_path, cut_path, coin_entry['angle_rev'], coin_entry['rev_crop_x'], coin_entry['rev_crop_y'], coin_entry['rev_crop_r'])
            coin_entry['reverse_img'] = f"/images/{cut_name}"

        # 📌 C. 处理【边齿】长条图 (无需圆形切片)
        file_edge = request.files.get('edge_img')
        if file_edge:
            edge_name = f"edge_{timestamp}_{file_edge.filename}"
            edge_path = os.path.join(IMAGE_DIR, edge_name)
            file_edge.save(edge_path)
            
            # 如果边齿有单纯的无损旋转要求，应用旋转并保存
            rot_edge = coin_entry['angle_edge']
            if abs(rot_edge) > 0.01:
                with Image.open(edge_path) as e_img:
                    e_img = ImageOps.exif_transpose(e_img)
                    e_img = e_img.rotate(-rot_edge, expand=True)
                    e_img.save(edge_path)
                    
            coin_entry['edge_img'] = f"/images/{edge_name}"

        # 📌 D. 批量吞入追加的细节特征随拍随贴图
        uploaded_extras = request.files.getlist('extra_imgs')
        for i, file_ex in enumerate(uploaded_extras):
            if file_ex and file_ex.filename != '':
                filename = f"extra_{timestamp}_{i}_{file_ex.filename}"
                file_ex.save(os.path.join(IMAGE_DIR, filename))
                coin_entry['extra_imgs'].append(f"/images/{filename}")

        # 覆写或追加数据
        if idx != -1 and 0 <= idx < len(coins):
            coins[idx] = coin_entry
        else:
            coins.append(coin_entry)
            
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(coins, f, ensure_ascii=False, indent=2)
            
        return jsonify({"status": "success", "message": "iPhone 旋转物理扶正并完美秒抠成功！"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# 3. 删除某枚藏品
@app.route('/api/delete-coin', methods=['POST'])
def delete_coin():
    try:
        req = request.json
        idx = int(req.get('index', -1))
        if not os.path.exists(DATA_FILE): return jsonify({"success": False})
        with open(DATA_FILE, 'r', encoding='utf-8') as f: 
            coins = json.load(f)
        if 0 <= idx < len(coins):
            coins.pop(idx)
            with open(DATA_FILE, 'w', encoding='utf-8') as f: 
                json.dump(coins, f, ensure_ascii=False, indent=2)
            return jsonify({"success": True})
        return jsonify({"success": False})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

if __name__ == '__main__':
    print("\n" + "="*50)
    print(" 泉府遗珍 · 藏品打理大脑正在启动，服务端口: http://127.0.0.1:8000")
    print("="*50 + "\n")
    app.run(host='0.0.0.0', port=8000, debug=True)