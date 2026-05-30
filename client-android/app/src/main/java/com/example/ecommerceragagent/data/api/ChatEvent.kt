package com.example.ecommerceragagent.data.api

import com.example.ecommerceragagent.data.model.Product

sealed interface ChatEvent {
    data class ProductFound(val product: Product) : ChatEvent
    data class Token(val content: String) : ChatEvent
    data object Done : ChatEvent
    data class Error(val message: String) : ChatEvent
}
