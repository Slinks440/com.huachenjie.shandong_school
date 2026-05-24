import hashlib
import base64
import time
import json
import math
import random
import os
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from curl_cffi import requests

# ================= 核心签名密钥 =================
AES_SIGN_KEY = b'RHXL092CDOYTQJVP' + b'\x00' * 16
AES_IV = b'01234ABCDEF56789'

def aes_encrypt(plaintext, key, iv):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    data = plaintext.encode('utf-8') if isinstance(plaintext, str) else plaintext
    padded_data = pad(data, AES.block_size, style='pkcs7')
    return base64.b64encode(cipher.encrypt(padded_data)).decode('utf-8')

def get_sign(params):
    keys = sorted(params.keys())
    raw_str = "".join([str(params[k]) for k in keys if k != 'sign'])
    sha256_hash = hashlib.sha256(raw_str.encode('utf-8')).hexdigest()
    return aes_encrypt(sha256_hash, AES_SIGN_KEY, AES_IV)

# ================= 几何与地理算法库 =================
def get_distance(lng1, lat1, lng2, lat2):
    """计算两点间的物理距离(米)"""
    rad_lat1, rad_lat2 = math.radians(lat1), math.radians(lat2)
    a = rad_lat1 - rad_lat2
    b = math.radians(lng1) - math.radians(lng2)
    s = 2 * math.asin(math.sqrt(math.sin(a/2)**2 + math.cos(rad_lat1)*math.cos(rad_lat2)*math.sin(b/2)**2))
    return s * 6378137.0

def move_towards(curr_lng, curr_lat, target_lng, target_lat, step_distance):
    """沿着目标方向移动指定距离"""
    dist = get_distance(curr_lng, curr_lat, target_lng, target_lat)
    if dist <= step_distance:
        return target_lng, target_lat, dist
    ratio = step_distance / dist
    new_lng = curr_lng + (target_lng - curr_lng) * ratio
    new_lat = curr_lat + (target_lat - curr_lat) * ratio
    return new_lng, new_lat, step_distance

def load_accounts():
    """从 config.json 加载所有账号信息"""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if not os.path.exists(config_path):
        print("config.json 不存在，请先运行登录脚本生成配置文件。")
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

def select_account(accounts):
    """在终端选择要使用的账号"""
    if not accounts:
        print("没有可用的账号。")
        return None
    phones = list(accounts.keys())
    print("\n可用账号列表：")
    for idx, phone in enumerate(phones, 1):
        print(f"  {idx}. {phone}")
    while True:
        try:
            choice = input("请选择账号序号（输入数字）: ").strip()
            if not choice:
                continue
            idx = int(choice) - 1
            if 0 <= idx < len(phones):
                selected_phone = phones[idx]
                print(f"已选择账号: {selected_phone}")
                return selected_phone, accounts[selected_phone]
            else:
                print("序号超出范围，请重新输入。")
        except ValueError:
            print("请输入有效数字。")

class GhostRunner:
    def __init__(self, token, satoken, school_code, device_id="dc01dabdd5e861e3"):
        self.session = requests.Session()
        self.token = token
        self.satoken = satoken
        self.school_code = school_code
        self.device_id = device_id

        # 下面这些会在后续动态获取
        self.run_plan_code = None
        self.fence_code = None
        self.fence_boundary = []       # 围栏多边形顶点
        self.sub_school_code = None    # 校区代码
        self.face_img = ""
        self.target_points = []
        self.run_record_code = None

        self.base_headers = {
            "Host": "api.huachenjie.com",
            "Connection": "Keep-Alive",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "ShanDong/8.6.0 (Redmi;Android 13)",
            "Accept-Encoding": "gzip",
            "app": "run-front",
            "Authorization": self.token,
            "satoken": self.satoken
        }

    def _post(self, url, payload, v_param):
        headers = self.base_headers.copy()
        headers.update({"e": "0", "v": v_param, "pv": "2", "api": "run", "k": ""})
        headers['sign'] = get_sign(payload)
        return self.session.post(url, json=payload, headers=headers, impersonate="chrome110").json()

    def _get_plan_code(self):
        """获取当前学期跑步计划代码"""
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
        res = self._post(url, payload, "plan")
        if res.get("code") == 0:
            plans = res.get("data", {}).get("list", [])
            if plans:
                plan = plans[0]
                self.run_plan_code = plan.get("runPlanCode")
                print(f"当前学期计划: {plan.get('runPlanName')} (code: {self.run_plan_code})")
                return True
        print("获取学期计划失败，请检查账号状态。")
        return False

    def _get_fence_data(self):
        """获取学校围栏列表，让用户选择跑步区域"""
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
        # 注意这里 api 是 school，所以 _post 里的 api 固定为 run 需要修改一下
        headers = self.base_headers.copy()
        headers.update({"e": "0", "v": "querySchoolFences", "pv": "2", "api": "school", "k": ""})
        headers['sign'] = get_sign(payload)
        res = self.session.post(url, json=payload, headers=headers, impersonate="chrome110").json()

        if res.get("code") != 0:
            print("获取围栏数据失败:", res.get("message"))
            return False

        fences = res.get("data", [])
        if not fences:
            print("该学校没有可用的跑步区域。")
            return False

        print("\n学校围栏列表：")
        for idx, fence in enumerate(fences, 1):
            name = fence.get("fenceName", "未知")
            sub = fence.get("subSchoolName", "")
            print(f"  {idx}. {name} ({sub})")

        while True:
            try:
                choice = input("请选择跑步区域序号: ").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(fences):
                    selected = fences[idx]
                    self.fence_code = selected.get("fenceCode")
                    self.fence_boundary = selected.get("fenceList", [])
                    # 尝试获取校区代码（不同学校字段名可能不同）
                    self.sub_school_code = selected.get("subSchoolCode", self.school_code)
                    print(f"已选择围栏: {selected.get('fenceName')} (code: {self.fence_code})")
                    return True
                else:
                    print("序号超出范围。")
            except ValueError:
                print("请输入数字。")

    def phase1_init_run(self):
        print("\n=== 准备跑步，获取规则 ===")

        # 1. 获取跑步配置、人脸底图
        config_payload = {
            "runPlanCode": self.run_plan_code,
            "appVersion": "8.6.0",
            "buildVersion": "26052214",
            "sportType": "1",
            "subSchoolCode": self.sub_school_code,
            "channel": "xiaomi",
            "targetDistance": "3000",
            "appCode": "SD001",
            "deviceId": self.device_id,
            "systemVersion": "13",
            "platform": "2",
            "modelName": "Xiaomi|22041211AC",
            "fenceCode": self.fence_code,
            "schoolCode": self.school_code,
            "timestamp": str(int(time.time() * 1000))
        }
        res_cfg = self._post("https://api.huachenjie.com/run-front/run/checkSunRunConfig", config_payload, "checkSunRunConfig")
        if res_cfg.get("code") != 0:
            print("获取跑步配置失败:", res_cfg.get("message"))
            return False
        self.face_img = res_cfg.get("data", {}).get("faceImg", "")
        print(f"获取到人脸底图: {self.face_img[:50]}...")

        # 2. 开始跑步
        start_payload = config_payload.copy()
        start_payload["useCreditSword"] = "false"
        # 起点用围栏第一个点
        if self.fence_boundary:
            start_payload["lng"] = str(self.fence_boundary[0]['lng'])
            start_payload["lat"] = str(self.fence_boundary[0]['lat'])
        else:
            print("围栏数据异常。")
            return False

        res_start = self._post("https://api.huachenjie.com/run-front/run/startSunRun_v2", start_payload, "startSunRun_v2")
        if res_start.get("code") != 0:
            print("开始跑步失败:", res_start.get("message"))
            return False

        data = res_start.get("data", {})
        self.run_record_code = data.get("runRecordCode")
        self.target_points = data.get("targetPoints", [])

        print(f" {self.run_record_code}")
        print(f"收到 {len(self.target_points)} 个必经打卡点。")
        return True

    def phase2_ghost_running(self):
        if not self.fence_boundary:
            print("无围栏边界，无法跑步。")
            return None, 0

        total_target_distance = 3010
        total_duration = 900
        speed_m_per_s = total_target_distance / total_duration

        # 起点取围栏第一个点
        current_lng = self.fence_boundary[0]['lng']
        current_lat = self.fence_boundary[0]['lat']
        current_distance = 0.0

        start_time_ms = int(time.time() * 1000)
        current_time_ms = start_time_ms

        poi_history = []
        pending_heartbeat_pois = []
        poi_index = 0

        # 必经打卡点列表
        route_goals = [{"lng": p["lng"], "lat": p["lat"], "code": p["code"]} for p in self.target_points]
        # 添加围栏中心点作为最终漫游目标
        center_lng = sum(p['lng'] for p in self.fence_boundary) / len(self.fence_boundary)
        center_lat = sum(p['lat'] for p in self.fence_boundary) / len(self.fence_boundary)
        route_goals.append({"lng": center_lng, "lat": center_lat, "code": "CENTER"})

        current_goal = route_goals.pop(0)

        print("脚本将以真实时间速率运行 15 分钟，请不要关闭程序...")

        for step_sec in range(0, total_duration, 3):
            step_dist = speed_m_per_s * 3
            current_lng, current_lat, moved_dist = move_towards(
                current_lng, current_lat, current_goal["lng"], current_goal["lat"], step_dist
            )
            current_distance += moved_dist
            current_time_ms += 3000

            # 判断是否到达目标点
            if get_distance(current_lng, current_lat, current_goal["lng"], current_goal["lat"]) < 10:
                if "code" in current_goal and current_goal["code"] != "CENTER":
                    # 寻找对应的目标点并打卡
                    for tp in self.target_points:
                        if tp["code"] == current_goal["code"] and not tp.get("passStatus"):
                            pass_payload = {
                                "runRecordCode": self.run_record_code,
                                "targetPoints": [{
                                    "code": tp['code'],
                                    "lng": tp['lng'],
                                    "lat": tp['lat'],
                                    "passStatus": True,
                                    "clockTime": current_time_ms
                                }],
                                "appVersion": "8.6.0", "buildVersion": "26052214",
                                "channel": "xiaomi", "appCode": "SD001", "deviceId": self.device_id,
                                "systemVersion": "13", "platform": "2", "modelName": "Xiaomi|22041211AC",
                                "timestamp": str(current_time_ms + 100)
                            }
                            resp = self._post(
                                "https://api.huachenjie.com/run-front/run/uploadPassPoint",
                                pass_payload, "uploadPassPoint"
                            )
                            print(f"触发打卡桩: {tp['code']} 验证通过！响应: {resp}")
                            tp['passStatus'] = True
                            tp['clockTime'] = current_time_ms
                            break

                # 切换到下一个目标
                if route_goals:
                    current_goal = route_goals.pop(0)
                else:
                    # 随机微调中心点继续跑
                    current_goal = {
                        "lng": center_lng + random.uniform(-0.001, 0.001),
                        "lat": center_lat + random.uniform(-0.001, 0.001)
                    }

            # 构造 POI
            poi = {
                "accuracy": round(random.uniform(1.0, 3.0), 1),
                "collectTime": current_time_ms - 200,
                "createTime": current_time_ms,
                "index": poi_index,
                "lat": current_lat,
                "lng": current_lng,
                "offFenceDisM": -1,
                "runTime": step_sec,
                "satellites": random.randint(12, 22),
                "state": 1
            }
            poi_history.append(poi)
            pending_heartbeat_pois.append(poi)
            poi_index += 1

            # 心跳包（每5个点发一次）
            if len(pending_heartbeat_pois) >= 5:
                hb_payload = {
                    "modelName": "Xiaomi|22041211AC", "appVersion": "8.6.0", "buildVersion": "26052214",
                    "channel": "xiaomi", "appCode": "SD001", "deviceId": self.device_id,
                    "systemVersion": "13", "platform": "2", "runRecordCode": self.run_record_code,
                    "pois": pending_heartbeat_pois, "timestamp": str(current_time_ms + 100)
                }
                self._post("https://api.huachenjie.com/run-front/run/uploadRunRecord", hb_payload, "uploadRunRecord")
                print(f"跑步包发送 | 进度: {step_sec//60:02d}分{step_sec%60:02d}秒 | 里程: {current_distance:.1f}m", end='\r')
                pending_heartbeat_pois = []

            time.sleep(3)

        print(f"\n3公里跑完了！总耗时: {total_duration}秒，准备跑步结算")
        return poi_history, current_distance

    def phase3_finish(self, poi_history, final_distance):
        if not self.target_points or not self.fence_boundary:
            print("跑步数据不完整，无法结算。")
            return

        total_steps = int(900 * (165 / 60))

        # 取最后几个定位点
        last_pois = poi_history[-4:] if len(poi_history) >= 4 else poi_history

        finish_payload = {
            "appVersion": "8.6.0", "stepInterval": 20, "distance": str(int(final_distance)),
            "channel": "xiaomi", "runImgRecord": "10e68b3196cbb448ab93811cad6a1a81",
            "targetPoints": self.target_points,
            "alignType": 3, "appCode": "SD001", "deviceId": self.device_id,
            "systemVersion": "13", "platform": "2", "duration": "900",
            "paceInterval": 50, "pauseCount": 0, "pois": last_pois,
            "faceCheckRecordList": [{
                "checkDistance": 1100, "randomDistance": 1104,
                "runFaceImg": self.face_img,
                "checkLng": self.target_points[0]['lng'], "checkLat": self.target_points[0]['lat'],
                "confidence": 88.88, "checkIndex": 1, "runFaceUpload": True,
                "popTime": int(time.time() * 1000) - 450000, "hasChecked": True,
                "finishFaceCheck": True, "rate": 1.0, "stability": 0,
                "extendParam": "{\"baseImageDownload\":1,\"similarityCheck\":1,\"uploadImage\":1}"
            }],
            "timestamp": str(int(time.time() * 1000)), "pauseTimes": 0, "buildVersion": "26052214",
            "sportType": 1, "totalStep": str(total_steps),
            "stepList": [{"endStep": total_steps, "index": 1, "startTime": 0, "step": total_steps, "endTime": 900, "startStep": 0, "time": 900, "stability": 0}],
            "runRecordCode": self.run_record_code, "modelName": "Xiaomi|22041211AC",
            "paceList": [{"endDistance": int(final_distance), "startDistance": 0, "distance": int(final_distance), "endStepCount": total_steps, "index": 1, "startTime": 0, "endTime": 900, "time": 900, "stepCount": total_steps, "stability": 0, "startStepCount": 0}],
            "status": 1
        }

        res = self._post("https://api.huachenjie.com/run-front/run/finishSunRun_v2", finish_payload, "finishSunRun_v2")
        print("\n==================================================")
        if res.get("code") == 0:
            print("跑步完成！结果:")
            print(json.dumps(res.get("data"), ensure_ascii=False, indent=2))
        else:
            print(f"结算失败: {res}")
        print("==================================================")

if __name__ == "__main__":
    accounts = load_accounts()
    if not accounts:
        exit(1)

    selected_phone, account_info = select_account(accounts)
    if not account_info:
        exit(1)

    runner = GhostRunner(
        token=account_info["auth_token"],
        satoken=account_info["sa_token"],
        school_code=account_info["school_code"],
        device_id=account_info.get("device_id", "dc01dabdd5e861e3")
    )

    # 动态获取学期计划与围栏
    if not runner._get_plan_code():
        exit(1)
    if not runner._get_fence_data():
        exit(1)

    if runner.phase1_init_run():
        pois, dist = runner.phase2_ghost_running()
        runner.phase3_finish(pois, dist)