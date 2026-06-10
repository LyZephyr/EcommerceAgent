package com.example.ecommerceragagent.data.api

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ChatApiServiceTest {
    private val service = ChatApiService(baseUrl = "http://127.0.0.1:8000")

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
                  "unavailable_reason": "商品已下架"
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
        assertEquals("http://127.0.0.1:8000/assets/p1.jpg", item.imageUrl)
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
