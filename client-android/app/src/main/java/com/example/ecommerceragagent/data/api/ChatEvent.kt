package com.example.ecommerceragagent.data.api

import com.example.ecommerceragagent.data.model.Cart
import com.example.ecommerceragagent.data.model.CompareTable
import com.example.ecommerceragagent.data.model.Product
import com.example.ecommerceragagent.data.model.StreamingStatus

sealed interface ChatEvent {
    data class StructuredStatus(val status: StreamingStatus) : ChatEvent
    data class CartUpdated(val cart: Cart) : ChatEvent
    data class MessageStart(val messageId: String, val attemptId: String) : ChatEvent
    data class MessageReset(val messageId: String, val attemptId: String, val reason: String) : ChatEvent
    data class MessageCommit(val messageId: String, val attemptId: String) : ChatEvent
    data class BlockText(val messageId: String, val attemptId: String, val blockId: String, val content: String) : ChatEvent
    data class BlockTextDelta(val messageId: String, val attemptId: String, val blockId: String, val content: String) : ChatEvent
    data class BlockProduct(val messageId: String, val attemptId: String, val blockId: String, val product: Product) : ChatEvent
    data class BlockCompare(val messageId: String, val attemptId: String, val blockId: String, val table: CompareTable) : ChatEvent
    data object Done : ChatEvent
    data class Error(val message: String) : ChatEvent
}
