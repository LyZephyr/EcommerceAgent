package com.example.ecommerceragagent.data.api

import com.example.ecommerceragagent.BuildConfig
import com.example.ecommerceragagent.data.model.Cart
import com.example.ecommerceragagent.data.model.CartItem
import com.example.ecommerceragagent.data.model.CompareProduct
import com.example.ecommerceragagent.data.model.CompareRow
import com.example.ecommerceragagent.data.model.CompareTable
import com.example.ecommerceragagent.data.model.ProductDetail
import com.example.ecommerceragagent.data.model.ProductFaq
import com.example.ecommerceragagent.data.model.ProductSpec
import com.example.ecommerceragagent.data.model.Product
import com.example.ecommerceragagent.data.model.ReviewSummary
import com.example.ecommerceragagent.data.model.StreamingStatus
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import org.json.JSONObject
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

class ChatApiService(
    private val baseUrl: String = BuildConfig.API_BASE_URL,
    private val client: OkHttpClient = OkHttpClient.Builder()
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
                        "status" -> trySend(ChatEvent.StructuredStatus(parseStatus(data)))
                        "cart" -> trySend(ChatEvent.CartUpdated(parseCart(data)))
                        "block" -> parseBlock(data)?.let { trySend(it) }
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

    suspend fun getCart(conversationId: String): Cart {
        val request = Request.Builder()
            .url("${apiBase()}/api/cart?conversation_id=${urlEncode(conversationId)}")
            .get()
            .build()
        return executeCartRequest(request)
    }

    suspend fun getProductDetail(productId: String): ProductDetail = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("${apiBase()}/api/products/${urlEncode(productId)}")
            .get()
            .build()

        client.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw IllegalStateException(parseErrorMessage(body, response.code))
            }
            parseProductDetail(body)
        }
    }

    suspend fun addCartItem(
        conversationId: String,
        productId: String,
        quantity: Int = 1
    ): Cart {
        val body = JSONObject()
            .put("conversation_id", conversationId)
            .put("product_id", productId)
            .put("quantity", quantity)
            .toString()
            .toRequestBody(jsonMediaType)

        val request = Request.Builder()
            .url("${apiBase()}/api/cart/items")
            .post(body)
            .build()
        return executeCartRequest(request)
    }

    suspend fun updateCartItem(
        conversationId: String,
        productId: String,
        quantity: Int
    ): Cart {
        val body = JSONObject()
            .put("conversation_id", conversationId)
            .put("quantity", quantity)
            .toString()
            .toRequestBody(jsonMediaType)

        val request = Request.Builder()
            .url("${apiBase()}/api/cart/items/${urlEncode(productId)}")
            .patch(body)
            .build()
        return executeCartRequest(request)
    }

    suspend fun removeCartItem(conversationId: String, productId: String): Cart {
        val request = Request.Builder()
            .url(
                "${apiBase()}/api/cart/items/${urlEncode(productId)}" +
                    "?conversation_id=${urlEncode(conversationId)}"
            )
            .delete()
            .build()
        return executeCartRequest(request)
    }

    suspend fun clearCart(conversationId: String): Cart {
        val request = Request.Builder()
            .url("${apiBase()}/api/cart?conversation_id=${urlEncode(conversationId)}")
            .delete()
            .build()
        return executeCartRequest(request)
    }

    private suspend fun executeCartRequest(request: Request): Cart = withContext(Dispatchers.IO) {
        client.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw IllegalStateException(parseErrorMessage(body, response.code))
            }
            parseCart(body)
        }
    }

    internal fun parseBlock(data: String): ChatEvent? {
        val json = JSONObject(data)
        val blockType = json.getString("type")
        val messageId = json.optString("message_id")
        val blockId = json.optString("block_id")

        return when (blockType) {
            "text" -> ChatEvent.BlockText(
                messageId = messageId,
                blockId = blockId,
                content = json.optString("content")
            )
            "text_delta" -> ChatEvent.BlockTextDelta(
                messageId = messageId,
                blockId = blockId,
                content = json.optString("content")
            )
            "product" -> ChatEvent.BlockProduct(
                messageId = messageId,
                blockId = blockId,
                product = parseProduct(json.getJSONObject("product"))
            )
            "compare" -> ChatEvent.BlockCompare(
                messageId = messageId,
                blockId = blockId,
                table = parseCompareTable(json.getJSONObject("compare"))
            )
            else -> null
        }
    }

    private fun parseStatus(data: String): StreamingStatus {
        val json = JSONObject(data)
        return StreamingStatus(
            phase = json.optString("phase"),
            message = json.optString("message"),
            step = json.optIntOrNull("step"),
            totalSteps = json.optIntOrNull("total_steps")
        )
    }

    private fun parseCompareTable(json: JSONObject): CompareTable {
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

    private fun parseProduct(json: JSONObject): Product {
        return Product(
            productId = json.getString("product_id"),
            title = json.getString("title"),
            category = json.getString("category"),
            price = json.getDouble("price"),
            brand = json.optStringOrNull("brand"),
            subCategory = json.optStringOrNull("sub_category"),
            imageUrl = absoluteImageUrl(json.optStringOrNull("image_url")),
            stock = json.optIntOrNull("stock"),
            detailUrl = absoluteApiUrl(json.optStringOrNull("detail_url")),
            landingUrl = json.optStringOrNull("landing_url"),
            highlights = json.optStringList("highlights"),
            stockStatus = json.optStringOrNull("stock_status"),
            unavailableReason = json.optStringOrNull("unavailable_reason"),
            groupLabel = json.optStringOrNull("group_label")
        )
    }

    internal fun parseProductDetail(data: String): ProductDetail {
        val json = JSONObject(data)
        val specsJson = json.optJSONArray("specs")
        val specs = buildList {
            if (specsJson != null) {
                for (index in 0 until specsJson.length()) {
                    val specJson = specsJson.getJSONObject(index)
                    add(
                        ProductSpec(
                            name = specJson.optString("name"),
                            value = specJson.optString("value")
                        )
                    )
                }
            }
        }
        val faqJson = json.optJSONArray("faq")
        val faq = buildList {
            if (faqJson != null) {
                for (index in 0 until faqJson.length()) {
                    val itemJson = faqJson.getJSONObject(index)
                    add(
                        ProductFaq(
                            question = itemJson.optString("question"),
                            answer = itemJson.optString("answer")
                        )
                    )
                }
            }
        }
        val reviewJson = json.optJSONObject("review_summary")
        val reviewSummary = reviewJson?.let {
            ReviewSummary(
                averageRating = it.optDoubleOrNull("average_rating"),
                totalCount = it.optIntOrNull("total_count"),
                highlights = it.optStringList("highlights")
            )
        }

        return ProductDetail(
            product = parseProduct(json),
            description = json.optStringOrNull("description"),
            specs = specs,
            faq = faq,
            reviewSummary = reviewSummary
        )
    }

    internal fun parseCart(data: String): Cart {
        val json = JSONObject(data)
        val itemsJson = json.getJSONArray("items")
        val items = buildList {
            for (index in 0 until itemsJson.length()) {
                val itemJson = itemsJson.getJSONObject(index)
                add(
                    CartItem(
                        productId = itemJson.getString("product_id"),
                        title = itemJson.getString("title"),
                        category = itemJson.getString("category"),
                        price = itemJson.getDouble("price"),
                        brand = itemJson.optStringOrNull("brand"),
                        subCategory = itemJson.optStringOrNull("sub_category"),
                        imageUrl = absoluteImageUrl(itemJson.optStringOrNull("image_url")),
                        quantity = itemJson.getInt("quantity"),
                        stock = itemJson.optIntOrNull("stock"),
                        isActive = itemJson.optBooleanOrNull("is_active"),
                        unavailableReason = itemJson.optStringOrNull("unavailable_reason"),
                        detailUrl = absoluteApiUrl(itemJson.optStringOrNull("detail_url")),
                        landingUrl = itemJson.optStringOrNull("landing_url"),
                        highlights = itemJson.optStringList("highlights"),
                        stockStatus = itemJson.optStringOrNull("stock_status")
                    )
                )
            }
        }
        val messages = if (json.has("messages") && !json.isNull("messages")) {
            val messagesJson = json.getJSONArray("messages")
            buildList {
                for (index in 0 until messagesJson.length()) {
                    messagesJson.optString(index).takeIf { it.isNotBlank() }?.let(::add)
                }
            }
        } else {
            emptyList()
        }

        return Cart(
            conversationId = json.getString("conversation_id"),
            items = items,
            totalQuantity = json.getInt("total_quantity"),
            totalPrice = json.getDouble("total_price"),
            messages = messages
        )
    }

    private fun absoluteImageUrl(imageUrl: String?): String? {
        if (imageUrl == null || imageUrl.startsWith("http://") || imageUrl.startsWith("https://")) {
            return imageUrl
        }
        return "${apiBase()}/${imageUrl.trimStart('/')}"
    }

    private fun absoluteApiUrl(url: String?): String? {
        if (url == null || url.startsWith("http://") || url.startsWith("https://")) {
            return url
        }
        return "${apiBase()}/${url.trimStart('/')}"
    }

    private fun parseErrorMessage(body: String, statusCode: Int): String {
        if (body.isBlank()) {
            return "HTTP $statusCode"
        }
        val detail = JSONObject(body).optStringOrNull("detail")
        return detail ?: "HTTP $statusCode"
    }

    private fun apiBase(): String = baseUrl.trimEnd('/')

    private fun urlEncode(value: String): String {
        return URLEncoder.encode(value, Charsets.UTF_8.name())
    }

    private fun JSONObject.optStringOrNull(name: String): String? {
        if (!has(name) || isNull(name)) {
            return null
        }
        return optString(name).takeIf { it.isNotBlank() }
    }

    private fun JSONObject.optIntOrNull(name: String): Int? {
        if (!has(name) || isNull(name)) {
            return null
        }
        return optInt(name)
    }

    private fun JSONObject.optDoubleOrNull(name: String): Double? {
        if (!has(name) || isNull(name)) {
            return null
        }
        return optDouble(name)
    }

    private fun JSONObject.optBooleanOrNull(name: String): Boolean? {
        if (!has(name) || isNull(name)) {
            return null
        }
        return optBoolean(name)
    }

    private fun JSONObject.optStringList(name: String): List<String> {
        if (!has(name) || isNull(name)) {
            return emptyList()
        }
        val array = optJSONArray(name) ?: return emptyList()
        return buildList {
            for (index in 0 until array.length()) {
                array.optString(index).takeIf { it.isNotBlank() }?.let(::add)
            }
        }
    }
}
