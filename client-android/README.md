# Android 客户端

Kotlin + Jetpack Compose 实现的电商导购聊天客户端，通过 OkHttp SSE 消费 `/api/chat` 流式事件，REST 调用商品详情与购物车接口。

## 后端地址配置

API 基址定义在 `app/build.gradle.kts`：

```kotlin
buildConfigField("String", "API_BASE_URL", "\"http://192.168.188.128:8000\"")
```

`ChatApiService` 默认读取 `BuildConfig.API_BASE_URL`。联调前**必须**改成你环境中的可达地址：

| 场景 | 地址示例 |
|------|----------|
| 模拟器 → 宿主机 | `http://10.0.2.2:8000` |
| 真机 → 局域网后端 | `http://192.168.x.x:8000` |

`AndroidManifest.xml` 已开启 `usesCleartextTraffic="true"`，允许 HTTP 明文访问（开发联调用）。

相对路径的图片与 API URL（如 `/assets/...`、`/api/products/...`）会在客户端拼成 `API_BASE_URL` 绝对地址。

## 会话 ID

`ChatViewModel` 在本地用 `UUID.randomUUID()` 生成 `conversationId`，聊天与购物车请求均携带该 ID。服务端 SSE **不会**回传 conversation_id。

## 功能

- 流式聊天：处理 `status` / `block` / `cart` / `done` / `error` SSE 事件
- 消息块：`TextBlock`、`ProductBlock`、`CompareBlock`
- 商品详情弹层：`GET /api/products/{id}`
- 购物车：查看、加购、改量、删除、清空（REST）
- 取消回复：取消协程 Job，断开 SSE

## 构建

```bash
cd client-android
./gradlew assembleDebug
```

Windows：

```powershell
.\gradlew.bat assembleDebug
```

Debug 签名使用项目内 `app/debug.keystore`（storePassword/keyPassword 均为 `android`）。

启动 App 前请确保后端已在 `API_BASE_URL` 对应端口运行。
