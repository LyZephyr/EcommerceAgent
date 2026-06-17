package com.example.ecommerceragagent.data.api

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatApiServiceTest {
    private val service = ChatApiService(baseUrl = "http://127.0.0.1:8000")

    @Test
    fun parseBlock_readsTextDelta() {
        val event = service.parseBlock(
            """
            {
              "type": "text_delta",
              "message_id": "asst-1",
              "block_id": "blk-1",
              "content": "适合日常使用"
            }
            """.trimIndent()
        )

        assertTrue(event is ChatEvent.BlockTextDelta)
        val delta = event as ChatEvent.BlockTextDelta
        assertEquals("asst-1", delta.messageId)
        assertEquals("attempt-1", delta.attemptId)
        assertEquals("blk-1", delta.blockId)
        assertEquals("适合日常使用", delta.content)
    }

    @Test
    fun parseBlock_usesPayloadAttemptIdWhenPresent() {
        val event = service.parseBlock(
            """
            {
              "type": "text_delta",
              "message_id": "asst-1",
              "attempt_id": "attempt-2",
              "block_id": "blk-1",
              "content": "next"
            }
            """.trimIndent()
        )

        assertTrue(event is ChatEvent.BlockTextDelta)
        val delta = event as ChatEvent.BlockTextDelta
        assertEquals("attempt-2", delta.attemptId)
    }

    @Test
    fun parseMessageLifecycleEvents() {
        val start = service.parseMessageStart(
            """
            {
              "message_id": "asst-1",
              "attempt_id": "attempt-1",
              "provisional": true
            }
            """.trimIndent()
        )
        val reset = service.parseMessageReset(
            """
            {
              "message_id": "asst-1",
              "attempt_id": "attempt-1",
              "reason": "retry"
            }
            """.trimIndent()
        )
        val commit = service.parseMessageCommit(
            """
            {
              "message_id": "asst-1",
              "attempt_id": "attempt-2"
            }
            """.trimIndent()
        )

        assertEquals("asst-1", start.messageId)
        assertEquals("attempt-1", start.attemptId)
        assertEquals("asst-1", reset.messageId)
        assertEquals("attempt-1", reset.attemptId)
        assertEquals("retry", reset.reason)
        assertEquals("asst-1", commit.messageId)
        assertEquals("attempt-2", commit.attemptId)
    }

    @Test
    fun parseBlock_readsExpandedProductFields() {
        val event = service.parseBlock(
            """
            {
              "type": "product",
              "message_id": "asst-1",
              "block_id": "blk-2",
              "product": {
                "product_id": "p1",
                "title": "防晒霜",
                "brand": "Sun",
                "category": "美妆护肤",
                "sub_category": "防晒",
                "price": 99.0,
                "image_url": "/assets/p1.jpg",
                "stock": 2,
                "detail_url": "/api/products/p1",
                "landing_url": null,
                "highlights": ["清爽", "防水"],
                "stock_status": "low_stock",
                "unavailable_reason": null,
                "group_label": "防晒护肤"
              }
            }
            """.trimIndent()
        )

        assertTrue(event is ChatEvent.BlockProduct)
        val productEvent = event as ChatEvent.BlockProduct
        assertEquals("attempt-1", productEvent.attemptId)
        val product = productEvent.product
        assertEquals("p1", product.productId)
        assertEquals("http://127.0.0.1:8000/assets/p1.jpg", product.imageUrl)
        assertEquals("http://127.0.0.1:8000/api/products/p1", product.detailUrl)
        assertEquals(listOf("清爽", "防水"), product.highlights)
        assertEquals("low_stock", product.stockStatus)
        assertEquals("防晒护肤", product.groupLabel)
    }

    @Test
    fun parseProductDetail_readsDetailSections() {
        val detail = service.parseProductDetail(
            """
            {
              "product_id": "p1",
              "title": "防晒霜",
              "brand": "Sun",
              "category": "美妆护肤",
              "sub_category": "防晒",
              "price": 99.0,
              "image_url": null,
              "stock": 2,
              "detail_url": "/api/products/p1",
              "landing_url": null,
              "highlights": ["清爽"],
              "stock_status": "low_stock",
              "unavailable_reason": null,
              "description": "适合通勤和户外。",
              "specs": [{"name": "规格", "value": "50ml"}],
              "faq": [{"question": "敏感肌可用吗", "answer": "建议先局部试用"}],
              "review_summary": {
                "average_rating": 4.5,
                "total_count": 12,
                "highlights": ["不黏腻"]
              }
            }
            """.trimIndent()
        )

        assertEquals("防晒霜", detail.product.title)
        assertEquals("适合通勤和户外。", detail.description)
        assertEquals("规格", detail.specs.single().name)
        assertEquals("敏感肌可用吗", detail.faq.single().question)
        assertEquals(4.5, detail.reviewSummary?.averageRating ?: 0.0, 0.001)
        assertEquals(listOf("不黏腻"), detail.reviewSummary?.highlights)
    }

    @Test
    fun parseCart_readsAvailabilityFieldsAndMessages() {
        val cart = service.parseCart(
            """
            {
              "conversation_id": "conversation-1",
              "items": [
                {
                  "product_id": "p1",
                  "title": "防晒霜",
                  "brand": "Sun",
                  "category": "美妆护肤",
                  "sub_category": "防晒",
                  "price": 99.0,
                  "image_url": "/assets/p1.jpg",
                  "stock": 0,
                  "quantity": 1,
                  "is_active": false,
                  "unavailable_reason": "商品已下架",
                  "stock_status": "inactive",
                  "detail_url": "/api/products/p1",
                  "highlights": ["清爽"]
                }
              ],
              "total_quantity": 1,
              "total_price": 99.0,
              "messages": ["商品已下架，已从购物车移除"]
            }
            """.trimIndent()
        )

        assertEquals("conversation-1", cart.conversationId)
        assertEquals(listOf("商品已下架，已从购物车移除"), cart.messages)

        val item = cart.items.single()
        assertEquals(0, item.stock)
        assertEquals(false, item.isActive)
        assertEquals("商品已下架", item.unavailableReason)
        assertEquals("inactive", item.stockStatus)
        assertEquals("http://127.0.0.1:8000/assets/p1.jpg", item.imageUrl)
        assertEquals("http://127.0.0.1:8000/api/products/p1", item.detailUrl)
    }

    @Test
    fun parseCart_allowsLegacyCartPayloads() {
        val cart = service.parseCart(
            """
            {
              "conversation_id": "conversation-1",
              "items": [
                {
                  "product_id": "p1",
                  "title": "防晒霜",
                  "brand": null,
                  "category": "美妆护肤",
                  "sub_category": null,
                  "price": 99.0,
                  "image_url": null,
                  "quantity": 1
                }
              ],
              "total_quantity": 1,
              "total_price": 99.0
            }
            """.trimIndent()
        )

        assertEquals(emptyList<String>(), cart.messages)

        val item = cart.items.single()
        assertNull(item.stock)
        assertNull(item.isActive)
        assertNull(item.unavailableReason)
    }
}
