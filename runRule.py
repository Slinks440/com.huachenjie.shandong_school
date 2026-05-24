import hashlib
import base64
import time
import json
import os
import cv2
import numpy as np
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from curl_cffi import requests

# ================= 核心密钥区 =================
AES_PWD_KEY = b'F44B0282BEA83557' + b'\x00' * 16
AES_SIGN_KEY = b'RHXL092CDOYTQJVP' + b'\x00' * 16
AES_IV = b'01234ABCDEF56789'
SLIDER_NATIVE_KEY = b"Ukp3hmSe7BmMcgbE"
# ==============================================

def aes_encrypt(plaintext, key, iv):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    data = plaintext.encode('utf-8') if isinstance(plaintext, str) else plaintext
    padded_data = pad(data, AES.block_size, style='pkcs7')
    return base64.b64encode(cipher.encrypt(padded_data)).decode('utf-8')

def encrypt_point_json(raw_x):
    e_real = int(raw_x - 6.5)
    fake_E = e_real + 16.5
    data = {"x": fake_E, "y": 15}
    json_str = json.dumps(data, separators=(',', ':'))
    cipher = AES.new(SLIDER_NATIVE_KEY, AES.MODE_ECB)
    padded_data = pad(json_str.encode('utf-8'), AES.block_size, style='pkcs7')
    return base64.b64encode(cipher.encrypt(padded_data)).decode('utf-8')

def get_sign(params):
    keys = sorted(params.keys())
    raw_str = "".join([str(params[k]) for k in keys if k != 'sign'])
    sha256_hash = hashlib.sha256(raw_str.encode('utf-8')).hexdigest()
    return aes_encrypt(sha256_hash, AES_SIGN_KEY, AES_IV)

class ShandingApp:
    def __init__(self, phone, password, school_code=None):
        self.session = requests.Session()
        self.phone = phone
        self.password = password
        self.device_id = "dc01dabdd5e861e3"
        
        self.auth_token = None
        self.sa_token = None
        self.school_code = school_code
        
        # 尝试读取本地配置文件（多账号存储）
        self._load_config()
        
        self.base_headers = {
            "Host": "api.huachenjie.com",
            "Connection": "Keep-Alive",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "ShanDong/8.6.0 (Redmi;Android 13)",
            "Accept-Encoding": "gzip"
        }

    def _get_config_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

    def _load_config(self):
        """从 config.json 加载当前手机号对应的账号信息"""
        config_path = self._get_config_path()
        if not os.path.exists(config_path):
            return
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                all_configs = json.load(f)
            if not isinstance(all_configs, dict):
                return
            account_info = all_configs.get(self.phone)
            if account_info:
                self.auth_token = account_info.get("auth_token")
                self.sa_token = account_info.get("sa_token")
                self.school_code = account_info.get("school_code") or self.school_code
                self.device_id = account_info.get("device_id", self.device_id)
                print(f"已从 config.json 加载账号 {self.phone} 的缓存信息")
        except Exception as e:
            print(f"读取配置文件失败: {e}")

    def _save_config(self):
        """将当前账号信息保存到 config.json（多账号共存）"""
        config_path = self._get_config_path()
        # 读取现有配置
        all_configs = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    all_configs = json.load(f)
                if not isinstance(all_configs, dict):
                    all_configs = {}
            except Exception:
                all_configs = {}

        # 更新或添加当前账号
        all_configs[self.phone] = {
            "auth_token": self.auth_token,
            "sa_token": self.sa_token,
            "school_code": self.school_code,
            "device_id": self.device_id
        }

        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(all_configs, f, ensure_ascii=False, indent=2)
            print(f"账号 {self.phone} 的登录信息已保存到 config.json")
        except Exception as e:
            print(f"保存配置文件失败: {e}")

    def _check_token_valid(self):
        """简单的 token 有效性校验：尝试获取计划列表，成功则有效"""
        if not self.auth_token or not self.sa_token:
            return False
        try:
            url = "https://api.huachenjie.com/run-front/run/plan/selectList"
            payload = {
                "modelName": "Xiaomi|22041211AC",
                "appVersion": "8.6.0",
                "buildVersion": "26052214",
                "semesterCode": "",
                "channel": "xiaomi",
                "appCode": "SD001",
                "deviceId": self.device_id,
                "systemVersion": "13",
                "platform": "2",
                "timestamp": str(int(time.time() * 1000))
            }
            headers = self.base_headers.copy()
            headers.update({
                "app": "run-front",
                "Authorization": self.auth_token,
                "satoken": self.sa_token,
                "e": "0",
                "v": "plan",
                "pv": "2",
                "api": "run",
                "k": ""
            })
            headers['sign'] = get_sign(payload)
            res = self.session.post(url, json=payload, headers=headers, impersonate="chrome110").json()
            if res.get("code") == 0:
                return True
        except Exception:
            pass
        return False

    def run_login_flow(self):
        # 如果已有有效 token，直接复用
        if self._check_token_valid():
            print(f"账号 {self.phone} 的缓存 token 仍然有效，跳过登录流程")
            return True

        # 否则执行完整登录流程
        print("\n=== 阶段一：账号授权登录 ===")
        print("1. 发起验证码请求...")
        res_get = self.session.post(
            "https://api.huachenjie.com/run-front/captcha/get",
            json={"captchaType": "blockPuzzle", "timestamp": str(int(time.time() * 1000))},
            headers=self.base_headers,
            impersonate="chrome110"
        ).json()
        
        data = res_get.get("data", {})
        token = data.get("token")
        bg_url = data.get("originalImageUrl")
        fg_url = data.get("jigsawImageUrl")
        
        if not bg_url or not fg_url:
            print("获取验证码失败！")
            return False

        bg = cv2.imdecode(np.frombuffer(self.session.get(bg_url).content, np.uint8), cv2.IMREAD_GRAYSCALE)
        fg = cv2.imdecode(np.frombuffer(self.session.get(fg_url).content, np.uint8), cv2.IMREAD_UNCHANGED)
        x, y, w, h = cv2.boundingRect(fg[:,:,3])
        fg_gray = cv2.cvtColor(fg[y:y+h, x:x+w], cv2.COLOR_BGRA2GRAY)
        res = cv2.matchTemplate(cv2.Canny(bg, 100, 200), cv2.Canny(fg_gray, 100, 200), cv2.TM_CCOEFF_NORMED)
        _, _, _, max_loc = cv2.minMaxLoc(res)
        raw_x = max_loc[0]
        
        print("2. 开始提交滑块验证...")
        valid_point_cipher = None
        
        for offset in range(-2, 3):
            test_x = raw_x + offset
            encrypted_point = encrypt_point_json(test_x)
            check_payload = {
                "captchaType": "blockPuzzle",
                "pointJson": encrypted_point,
                "token": token
            }
            res_check = self.session.post(
                "https://api.huachenjie.com/run-front/captcha/check",
                json=check_payload, headers=self.base_headers, impersonate="chrome110"
            ).json()
            
            if res_check.get("data", {}).get("result") == True:
                print(f"校验通过，提取加密坐标: {encrypted_point}")
                valid_point_cipher = encrypted_point
                break
            time.sleep(0.5)
            
        if not valid_point_cipher:
            print("滑块验证失败。")
            return False
            
        print("3. 执行账号登录...")
        login_headers = self.base_headers.copy()
        login_headers.update({
            "app": "run-front",
            "e": "1",
            "v": "loginPassword",
            "pv": "2",
            "api": "auth",
            "k": ""
        })
        
        login_payload = {
            "modelName": "Xiaomi|22041211AC",
            "password": aes_encrypt(self.password, AES_PWD_KEY, AES_IV),
            "appVersion": "8.6.0",
            "buildVersion": "26052214",
            "loginName": self.phone,
            "channel": "xiaomi",
            "captchaPoint": valid_point_cipher,
            "appCode": "SD001",
            "deviceId": self.device_id,
            "systemVersion": "13",
            "platform": "2",
            "timestamp": str(int(time.time() * 1000))
        }
        
        login_payload['sign'] = get_sign(login_payload)
        res_login = self.session.post("https://api.huachenjie.com/run-front/auth/loginPassword",
                                      json=login_payload, headers=login_headers, impersonate="chrome110").json()
        
        if res_login.get("code") == 0:
            print("登录成功！成功获取鉴权 Token。")
            login_data = res_login.get("data", {})
            self.auth_token = login_data.get("token")
            self.sa_token = login_data.get("satoken")
            # 尝试自动获取学校代码
            if not self.school_code:
                self.school_code = login_data.get("schoolCode", "")
                if self.school_code:
                    print(f"已自动获取学校代码: {self.school_code}")
            # 保存到配置文件（多账号模式）
            self._save_config()
            return True
        else:
            print(f"登录失败: {res_login}")
            return False

    def fetch_dynamic_plan_code(self):
        url = "https://api.huachenjie.com/run-front/run/plan/selectList"
        payload = {
            "modelName": "Xiaomi|22041211AC",
            "appVersion": "8.6.0",
            "buildVersion": "26052214",
            "semesterCode": "",
            "channel": "xiaomi",
            "appCode": "SD001",
            "deviceId": self.device_id,
            "systemVersion": "13",
            "platform": "2",
            "timestamp": str(int(time.time() * 1000))
        }
        
        headers = self.base_headers.copy()
        headers.update({
            "app": "run-front", "Authorization": self.auth_token, "satoken": self.sa_token,
            "e": "0", "v": "plan", "pv": "2", "api": "run", "k": ""
        })
        headers['sign'] = get_sign(payload)
        
        res = self.session.post(url, json=payload, headers=headers, impersonate="chrome110").json()
        if res.get("code") == 0:
            plan_list = res.get("data", {}).get("list", [])
            if plan_list:
                current_plan = plan_list[0]
                plan_code = current_plan.get("runPlanCode")
                plan_name = current_plan.get("runPlanName")
                print(f"成功获取当前学期计划: 【{plan_name}】 (Code: {plan_code})")
                return plan_code
        print("获取动态计划编码失败！")
        return None

    def fetch_plan_rules_and_progress(self, plan_code):
        url = "https://api.huachenjie.com/run-front/run/querySunRunAbstractInfoV2"
        payload = {
            "modelName": "Xiaomi|22041211AC",
            "runPlanCode": plan_code,
            "appVersion": "8.6.0",
            "buildVersion": "26052214",
            "semesterCode": "",
            "sportType": "1",
            "channel": "xiaomi",
            "appCode": "SD001",
            "deviceId": self.device_id,
            "systemVersion": "13",
            "platform": "2",
            "timestamp": str(int(time.time() * 1000))
        }
        
        headers = self.base_headers.copy()
        headers.update({
            "app": "run-front", "Authorization": self.auth_token, "satoken": self.sa_token,
            "e": "0", "v": "querySunRunAbstractInfoV2", "pv": "2", "api": "run", "k": ""
        })
        headers['sign'] = get_sign(payload)
        
        res = self.session.post(url, json=payload, headers=headers, impersonate="chrome110").json()
        return res

    def display_dashboard(self):
        print("\n" + "="*50)
        print("闪动校园 - 跑步计划与进度")
        print("="*50)
        
        plan_code = self.fetch_dynamic_plan_code()
        if not plan_code:
            return None
            
        time.sleep(0.5)
        print("正在拉取学校跑步规则与个人进度...\n")
        info_res = self.fetch_plan_rules_and_progress(plan_code)
        
        if info_res.get("code") != 0:
            print(f"获取规则失败: {info_res.get('message')}")
            return plan_code
            
        data = info_res.get("data", {})
        rule = data.get("schoolDemandRule", {})
        progress = data.get("studentDoneRuleInfo", {})
        
        start_date = rule.get("startDate", "未知")
        end_date = rule.get("endDate", "未知")
        valid_times = rule.get("timeFragment", [{"times": "未知"}])[0].get("times", "未知")
        target_dist = round(rule.get("totalDistance", 0) / 1000.0, 2)
        min_dist = round(rule.get("singleMinDistance", 0) / 1000.0, 2)
        max_dist = round(rule.get("dayMaxDistance", 0) / 1000.0, 2)
        min_pace = f"{rule.get('minPace', 0) // 60}'{rule.get('minPace', 0) % 60:02d}\""
        max_pace = f"{rule.get('maxPace', 0) // 60}'{rule.get('maxPace', 0) % 60:02d}\""
        
        done_dist = round(progress.get("doneDistance", 0) / 1000.0, 2)
        done_percent = progress.get("donePercent", 0.0)
        valid_counts = progress.get("doneTargetTimes", 0)
        total_kcal = round(progress.get("totalCalorie", 0) / 1000.0, 1)

        print("【学校跑步规则】")
        print(f"  考核周期: {start_date} 至 {end_date}")
        print(f"  允许打卡时段: {valid_times}")
        print(f"  学期总目标: {target_dist} km")
        print(f"  单次有效里程: {min_dist} km ~ {max_dist} km")
        print(f"  允许配速范围: {max_pace} ~ {min_pace} /公里")
        print("-" * 50)
        print("【个人完成进度】")
        print(f"  已跑里程: {done_dist} km")
        print(f"  有效次数: {valid_counts} 次")
        print(f"  累计消耗: {total_kcal} kcal")
        print(f"  整体完成度: {done_percent}%")
        print("=" * 50 + "\n")
        
        return plan_code

    def get_records_by_page(self, plan_code, page_num):
        url = "https://api.huachenjie.com/run-front/run/pageSunRunRecord"
        payload = {
            "runPlanCode": plan_code,
            "appVersion": "8.6.0",
            "buildVersion": "26052214",
            "semesterCode": "",
            "channel": "xiaomi",
            "pageSize": "10",
            "appCode": "SD001",
            "pageNum": str(page_num),
            "deviceId": self.device_id,
            "systemVersion": "13",
            "platform": "2",
            "modelName": "Xiaomi|22041211AC",
            "timestamp": str(int(time.time() * 1000))
        }
        
        headers = self.base_headers.copy()
        headers.update({
            "app": "run-front", "Authorization": self.auth_token, "satoken": self.sa_token,
            "e": "0", "v": "pageSunRunRecord", "pv": "2", "api": "run", "k": ""
        })
        headers['sign'] = get_sign(payload)
        
        res = self.session.post(url, json=payload, headers=headers, impersonate="chrome110").json()
        return res

    def fetch_all_records(self, plan_code):
        print("=== 阶段三：拉取历史阳光晨跑记录 ===")
        print("-" * 105)
        
        page = 1
        total_records = 0
        total_distance = 0.0
        
        while True:
            response = self.get_records_by_page(plan_code, page)
            if response.get("code") != 0:
                print(f"请求失败: {response.get('message', '未知错误')}")
                break
                
            records = response.get("data", {}).get("list", [])
            if not records:
                break
                
            for idx, record in enumerate(records, 1):
                raw_distance = record.get("distance", 0)
                distance_km = round(raw_distance / 1000.0, 2)
                total_distance += distance_km
                
                raw_duration = record.get("duration", 0)
                minutes = raw_duration // 60
                seconds = raw_duration % 60
                time_str = f"{minutes}分{seconds:02d}秒"
                
                start_time_ms = int(record.get("startTime", 0))
                if start_time_ms > 0:
                    date_str = datetime.fromtimestamp(start_time_ms / 1000.0).strftime('%Y-%m-%d %H:%M')
                else:
                    date_str = "未知时间"
                    
                raw_pace = record.get("pace", 0)
                pace_min = raw_pace // 60
                pace_sec = raw_pace % 60
                pace_str = f"{pace_min}'{pace_sec:02d}\""
                
                steps = record.get("totalStep", 0)
                kcal = round(record.get("calorie", 0) / 1000.0, 1)
                status_code = record.get("sunRunRecordStatus", 1)
                valid = "有效" if status_code == 1 else "无效"
                
                print(f"[{page:02d}-{idx:02d}] {date_str} | 距离: {distance_km:>4.2f} km | 时长: {time_str:>7} | 配速: {pace_str:>6} | 步数: {steps:>4} | {kcal:>5.1f} kcal | 状态: {valid}")
                total_records += 1
                
            if len(records) < 10:
                break
                
            page += 1
            time.sleep(0.3)
            
        print("-" * 105)
        print(f"统计完成：共拉取 {total_records} 条记录，总跑步里程约 {round(total_distance, 2)} 公里！\n")

    def run(self):
        if self.run_login_flow():
            time.sleep(1)
            plan_code = self.display_dashboard()
            
            if plan_code:
                time.sleep(1)
                self.fetch_all_records(plan_code)
            
            # === 集成电子围栏查询 ===
            time.sleep(1)
            if self.school_code:
                print("\n>>> 开始查询学校电子围栏 <<<")
                fence_query = SunRunFenceQuery(
                    token=self.auth_token,
                    satoken=self.sa_token,
                    school_code=self.school_code
                )
                fence_query.fetch_fences()
            else:
                print("\n提示：未获取到学校代码，跳过电子围栏查询。")
                print("如需查询，请在创建ShandingApp实例时手动传入 school_code 参数。")


# ================= 电子围栏查询类 =================
class SunRunFenceQuery:
    def __init__(self, token, satoken, school_code):
        self.session = requests.Session()
        self.token = token
        self.satoken = satoken
        self.school_code = school_code
        self.device_id = "dc01dabdd5e861e3"
       
        self.base_headers = {
            "Host": "api.huachenjie.com",
            "Connection": "Keep-Alive",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "ShanDong/8.6.0 (Redmi;Android 13)",
            "Accept-Encoding": "gzip",
            "app": "run-front",
            "Authorization": self.token,
            "satoken": self.satoken,
            "e": "0",
            "v": "querySchoolFences",
            "pv": "2",
            "api": "school",
            "k": ""
        }

    def fetch_fences(self):
        print("\n" + "="*50)
        print("正在获取学校电子围栏数据...")
        print("="*50)
       
        url = "https://api.huachenjie.com/run-front/school/querySchoolFences"
       
        payload = {
            "modelName": "Xiaomi|22041211AC",
            "appVersion": "8.6.0",
            "buildVersion": "26052214",
            "channel": "xiaomi",
            "appCode": "SD001",
            "deviceId": self.device_id,
            "systemVersion": "13",
            "platform": "2",
            "schoolCode": self.school_code,
            "timestamp": str(int(time.time() * 1000))
        }
       
        headers = self.base_headers.copy()
        headers['sign'] = get_sign(payload)
       
        try:
            res = self.session.post(url, json=payload, headers=headers, impersonate="chrome110").json()
           
            if res.get("code") != 0:
                print(f"获取围栏失败: {res.get('message', '未知错误')}")
                return
               
            fences = res.get("data", [])
            if not fences:
                print("该学校未设置任何电子围栏数据！")
                return
               
            print(f"成功获取到 {len(fences)} 个合法跑步区域！\n")
           
            for idx, fence in enumerate(fences, 1):
                fence_name = fence.get("fenceName", "未知区域")
                sub_school = fence.get("subSchoolName", "未知校区")
                center_lng = fence.get("lng")
                center_lat = fence.get("lat")
                vertex_list = fence.get("fenceList", [])
               
                print(f"区域 {idx}: 【{fence_name}】 (所属: {sub_school})")
                print(f"中心坐标: 经度 {center_lng}, 纬度 {center_lat}")
                print(f"边界多边形顶点数: {len(vertex_list)} 个")
               
                for v_idx, vertex in enumerate(vertex_list, 1):
                    print(f" [{v_idx:>2}] 经度 {vertex['lng']:.6f}, 纬度 {vertex['lat']:.6f}")
               
                print("-" * 50)
               
            print("数据提取完毕")
           
        except Exception as e:
            print(f"网络请求异常: {str(e)}")


if __name__ == "__main__":
    # 示例1：账号1
    PHONE = "手机号"
    PASSWORD = "密码"
    app = ShandingApp(PHONE, PASSWORD)
    app.run()
