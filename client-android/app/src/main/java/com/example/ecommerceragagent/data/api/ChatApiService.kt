package com.example.ecommerceragagent.data.api

import com.example.ecommerceragagent.BuildConfig
import com.example.ecommerceragagent.data.model.Product
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class ChatApiService(
    private val baseUrl: String = BuildConfig.API_BASE_URL,
    client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)
        .build()
) {
    private val eventSourceFactory = EventSources.createFactory(client)
    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()

    fun streamChat(message: String, conversationId: String?): Flow<ChatEvent> = callbackFlow {
        val body = JSONObject()
            .put("message", message)
            .apply {
                if (conversationId != null) {
                    put("conversation_id", conversationId)
                }
            }
            .toString()
            .toRequestBody(jsonMediaType)

        val request = Request.Builder()
            .url("${baseUrl.trimEnd('/')}/api/chat")
            .post(body)
            .build()

        val eventSource = eventSourceFactory.newEventSource(
            request,
            object : EventSourceListener() {
                override fun onEvent(
                    eventSource: EventSource,
                    id: String?,
                    type: String?,
                    data: String
                ) {
                    when (type) {
                        "product" -> trySend(ChatEvent.ProductFound(parseProduct(data)))
                        "token" -> trySend(ChatEvent.Token(JSONObject(data).getString("content")))
                        "done" -> {
                            trySend(ChatEvent.Done)
                            close()
                        }
                    }
                }

                override fun onFailure(
                    eventSource: EventSource,
                    t: Throwable?,
                    response: Response?
                ) {
                    val status = response?.code?.let { "HTTP $it" }
                    val reason = t?.message ?: status ?: "请求失败"
                    trySend(ChatEvent.Error(reason))
                    close()
                }

                override fun onClosed(eventSource: EventSource) {
                    close()
                }
            }
        )

        awaitClose { eventSource.cancel() }
    }

    private fun parseProduct(data: String): Product {
        val json = JSONObject(data)
        return Product(
            productId = json.getString("product_id"),
            title = json.getString("title"),
            category = json.getString("category"),
            price = json.getDouble("price"),
            brand = json.optStringOrNull("brand"),
            subCategory = json.optStringOrNull("sub_category"),
            imageUrl = absoluteImageUrl(json.optStringOrNull("image_url"))
        )
    }

    private fun absoluteImageUrl(imageUrl: String?): String? {
        if (imageUrl == null || imageUrl.startsWith("http://") || imageUrl.startsWith("https://")) {
            return imageUrl
        }
        return "${baseUrl.trimEnd('/')}/${imageUrl.trimStart('/')}"
    }

    private fun JSONObject.optStringOrNull(name: String): String? {
        if (!has(name) || isNull(name)) {
            return null
        }
        return optString(name).takeIf { it.isNotBlank() }
    }
}
