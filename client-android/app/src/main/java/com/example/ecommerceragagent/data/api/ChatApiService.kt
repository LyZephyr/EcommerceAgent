package com.example.ecommerceragagent.data.api

import com.example.ecommerceragagent.BuildConfig
import com.example.ecommerceragagent.data.model.CompareProduct
import com.example.ecommerceragagent.data.model.CompareRow
import com.example.ecommerceragagent.data.model.CompareTable
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
                        "status" -> trySend(ChatEvent.Status(JSONObject(data).getString("message")))
                        "product" -> trySend(ChatEvent.ProductFound(parseProduct(data)))
                        "compare" -> trySend(ChatEvent.Compare(parseCompareTable(data)))
                        "token" -> trySend(ChatEvent.Token(JSONObject(data).getString("content")))
                        "done" -> {
                            trySend(ChatEvent.Done)
                            close()
                        }
                        "error" -> {
                            trySend(ChatEvent.Error(JSONObject(data).getString("message")))
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

    private fun parseCompareTable(data: String): CompareTable {
        val json = JSONObject(data)
        val productsJson = json.getJSONArray("products")
        val products = buildList {
            for (index in 0 until productsJson.length()) {
                val productJson = productsJson.getJSONObject(index)
                add(
                    CompareProduct(
                        productId = productJson.getString("product_id"),
                        title = productJson.getString("title")
                    )
                )
            }
        }

        val rowsJson = json.getJSONArray("rows")
        val rows = buildList {
            for (index in 0 until rowsJson.length()) {
                val rowJson = rowsJson.getJSONObject(index)
                val valuesJson = rowJson.getJSONObject("values")
                val values = buildMap {
                    valuesJson.keys().forEach { productId ->
                        put(productId, valuesJson.optString(productId))
                    }
                }
                add(
                    CompareRow(
                        dimension = rowJson.getString("dimension"),
                        values = values
                    )
                )
            }
        }

        return CompareTable(products = products, rows = rows)
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
