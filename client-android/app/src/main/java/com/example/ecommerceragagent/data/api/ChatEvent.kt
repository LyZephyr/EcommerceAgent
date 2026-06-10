package com.example.ecommerceragagent.data.api

import com.example.ecommerceragagent.data.model.Cart
import com.example.ecommerceragagent.data.model.CompareTable
import com.example.ecommerceragagent.data.model.Product

sealed interface ChatEvent {
    data class Status(val message: String) : ChatEvent
    data class CartUpdated(val cart: Cart) : ChatEvent
    data class ProductFound(val product: Product) : ChatEvent
    data class Compare(val table: CompareTable) : ChatEvent
    data class Token(val content: String) : ChatEvent
    data object Done : ChatEvent
    data class Error(val message: String) : ChatEvent
}
