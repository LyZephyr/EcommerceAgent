package com.example.ecommerceragagent.data.model

import java.util.UUID

enum class MessageRole {
    User,
    Assistant
}

sealed interface MessageBlock {
    val id: String

    data class TextBlock(
        override val id: String,
        val content: String
    ) : MessageBlock

    data class ProductBlock(
        override val id: String,
        val product: Product
    ) : MessageBlock

    data class CompareBlock(
        override val id: String,
        val table: CompareTable
    ) : MessageBlock
}

data class Message(
    val id: String = UUID.randomUUID().toString(),
    val role: MessageRole,
    val blocks: List<MessageBlock>,
    val isStreaming: Boolean = false,
    val isError: Boolean = false,
    val interrupted: Boolean = false
)

data class StreamingStatus(
    val phase: String,
    val message: String,
    val step: Int?,
    val totalSteps: Int?
)
