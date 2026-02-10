群webhook机器人接口
在群组中添加webhook机器人并 获取webhook地址
一、请求格式说明
请求方式： POST

请求地址：

https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=xxx&channel=xxx

认证方式：IP白名单

请求参数：

{
    "messageType":"text",  
    "content":{
       "text":"@mettjhfuukaq@562a847505 有告警消息请查收一下"
    },
    "timeStamp":1669945732253,
    "uuid":"2b5a9091d2154c8eaeab7f9ed4d87697",
    "isAt": true,
    "isAtAll": false,
    "atAccounts": [
        "mettjhfuukaq@562a847505"
    ]
}
请求参数说明

参数	是否必选	参数类型	说明
token	是	String	访问token
channel	是	String	渠道来源：standard
messageType	是	String	消息类型：
text: 文本消息
content	是	Object	消息内容（@userid 或者@all、@所有人 可以解析成人名高亮显示），要确保userid与atAccounts中包含此人员才能实现高亮
content.text	是	String	消息文本内容，
内容长度范围（1~500）
timeStamp	是	Long	时间戳（10分钟内有效），请使用毫秒。
uuid	是	String	UUID字段全局唯一，
接口调用前需要重新生成UUID
isAt	否	Boolean	是否@某个人
isAtAll	否	Boolean	是否@全员
atAccounts	否（isAt为True时必填）	Array	被@人员的userid列表（当isAt为true时不能为空，且最多只支持10个账号）。注意：传入错误的userid将无法收到消息。
请求示例：

curl -X POST \
'https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=a69f751172bb4a36abe5de9ddf9aa1cc&channel=standard' \
-H 'Accept-Charset: UTF-8' \
-H 'Content-Type: application/json' \
-d'{
    "messageType":"text",  
    "content":{
       "text":"@mettjhfuukaq@562a847505 有告警消息请查收一下"
    },
    "timeStamp":1669945732253,
    "uuid":"2b5a9091d2154c8eaeab7f9ed4d87697",
    "isAt": true,
    "isAtAll": false,
    "atAccounts": ["mettjhfuukaq@562a847505"]
}'
二、响应格式说明
参数	参数类型	说明
code	String	错误码，见第三大点异常编码
data	String	字符串
message	String	消息
响应结果：

{
    "code": "0",
    "data": "success",
    "message": "ok"
}
三、异常编码
异常编码	描述
0	服务正常
58404	机器人资源不存在
58500	服务异常
58601	参数错误
58602	机器人未启用
