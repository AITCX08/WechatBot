import requests
import urllib.parse

def ck(type, a, school, user, passw, noun, kcid):
    if type == "haha":
        data = {
            "uid": a["user"],
            "key": a["pass"],
            "school": school,
            "user": user,
            "pass": passw,
            "platform": noun,
            "kcid": kcid
        }
        dx_rl = a["url"]
        dx_url = f"{dx_rl}/api.php?act=get"
        response = requests.post(dx_url, data=data)
        result = response.json()
        print(result)

        # 提取课程名称
        course_names = [course['name'] for course in result.get('data', [])]
        return course_names


def xd(type, a, school, user, passw, noun, kcname, kcid):
    if type == "haha":
        data = {
            "uid": a["user"],
            "key": a["pass"],
            "platform": noun,
            "school": school,
            "user": user,
            "pass": passw,
            "kcname": kcname,
            "kcid": kcid
        }
        dx_rl = a["url"]
        dx_url = f"{dx_rl}/api.php?act=add"
        response = requests.post(dx_url, data=data)
        result = response.json()
        print(result)

        if result.get("code") == "0":
            b = {"code": 1, "msg": "下单成功"}
        else:
            b = {"code": -1, "msg": result.get("msg", "未知错误")}

        return b


def jd(type, a, kcname, user, d):
    if type == "haha":
        uu_rl = a["url"]
        kcname_encoded = urllib.parse.quote(kcname)
        user_encoded = urllib.parse.quote(user)
        uu_url = f"{uu_rl}/api/search?uid={a['user']}&key={a['pass']}&kcname={kcname_encoded}&username={user_encoded}&cid={d['noun']}"

        response = requests.get(uu_url)
        result = response.json()

        print("Server Response:", result)  # 打印服务器返回的内容

        b = []
        if result.get("code") == "1":
            data = result.get("data")
            if data is not None:
                for res in data:
                    yid = res.get("id")
                    kcname = res.get("kcname")
                    status = res.get("status")
                    process = res.get("process")
                    remarks = res.get("remarks")
                    kcks = res.get("courseStartTime")
                    kcjs = res.get("courseEndTime")
                    ksks = res.get("examStartTime")
                    ksjs = res.get("examEndTime")
                    zhgx = res.get("zhgx")
                    b.append({
                        "code": 1,
                        "msg": "查询成功",
                        "yid": yid,
                        "kcname": kcname,
                        "user": user,
                        "pass": passw,  # 注意这里缺少变量passw的定义，需要传入或者修正
                        "ksks": ksks,
                        "ksjs": ksjs,
                        "status_text": status,
                        "process": process,
                        "remarks": remarks,
                        "zhgx": zhgx
                    })
            else:
                b.append({"code": -1, "msg": "数据为空"})
        else:
            b.append({"code": -1, "msg": result.get("msg", "未知错误")})

        return b


def cs(type, a, yid):
    if type == "haha":
        data = {
            "uid": a["user"],
            "key": a["pass"],
            "id": yid
        }
        dx_rl = a["url"]
        dx_url = f"{dx_rl}/api.php?act=budan"
        response = requests.post(dx_url, data=data)
        result = response.json()

        return result


# 使用示例
a = {
    "user": "1492246",
    "pass": "IZ0IPKM5pYPhhGqy",
    "url": "http://lxuexi.cn"
}
school = "吉林师范大学"
user = "18543480551"
passw = "wjx20010425"
noun = "1800"
d = {
    "noun": "1195"
}
kcid = "46"
kcname = "2024春季形势与政策"
yid = "123456"

# result = ck("haha", a, school, user, passw, noun, kcid)
# result = xd("haha", a, school, user, passw, noun, kcname, kcid)
# result = cs("haha", a, yid)
result = jd("haha", a, kcname, user, d)
print(result)