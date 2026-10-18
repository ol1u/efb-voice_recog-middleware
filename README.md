# VoiceRecogMiddleware: A middleware for EFB 

## Original Project

本项目基于：https://github.com/ehForwarderBot/efb-voice_recog-middleware

## Changes

1. 保证了只发送一次包括识别的语音，不重复发送
2. 只启用一个识别引擎时：去除语音识别工具的名称、去除第一个多余回车
3. 去除结尾的句号。
4. 删除了'recog`'命令（使用此命令原仓库可满足需求）
5. 修复多实例时识别引擎串用，以及临时音频文件未关闭的问题
6. 所有云端请求都有超时；讯飞连接或回调异常时不会永久等待
7. 百度 token 按有效期自动刷新，不再依赖重启
8. 识别失败不再被当作正常识别结果写入消息正文
9. 腾讯粤语配置使用 `16k_zh-PY` 中英粤混合引擎

## Installation

```
pip install git+https://github.com/ol1u/efb-voice_recog-middleware/
```

## Configuration

The configuration keeps the original `speech_api` structure. The following
example enables Azure, disables the Baidu fork entirely, and sets an optional
request timeout:

```yaml
request_timeout: 20
speech_api:
  azure:
    enabled: true
    key1: KEY_1
    endpoint: ENDPOINT
    lang: zh-CN
    # request_timeout: 15
  baidu:
    enabled: false
```

`request_timeout` is in seconds. The engine-specific value takes precedence,
then the top-level value, then the built-in default of 20 seconds. Existing
configurations without `enabled` keep their original behaviour. An engine is
loaded only when its section exists and `enabled` is not `false`.

For Tencent Speech, `lang: ca` selects the `16k_zh-PY` engine, which recognises
Chinese, English, and Cantonese in mixed speech:

```yaml
speech_api:
  tencent:
    secret_id: YOUR_SECRET_ID
    secret_key: YOUR_SECRET_KEY
    lang: ca
```
