package com.example.ecommerceragagent.data.model

import java.util.UUID

enum class MessageRole {
    User,
    Assistant
}

data class Message(
    val id: String = UUID.randomUUID().toString(),
    val role: MessageRole,
    val content: String,
    val products: List<Product> = emptyList(),
    val isStreaming: Boolean = false,
    val isError: Boolean = false
)
