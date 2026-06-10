package com.example.ecommerceragagent.data.model

data class CartItem(
    val productId: String,
    val title: String,
    val category: String,
    val price: Double,
    val brand: String?,
    val subCategory: String?,
    val imageUrl: String?,
    val quantity: Int
) {
    val subtotal: Double
        get() = price * quantity
}

data class Cart(
    val conversationId: String,
    val items: List<CartItem>,
    val totalQuantity: Int,
    val totalPrice: Double
) {
    companion object {
        fun empty(conversationId: String) = Cart(
            conversationId = conversationId,
            items = emptyList(),
            totalQuantity = 0,
            totalPrice = 0.0
        )
    }
}
