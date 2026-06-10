package com.example.ecommerceragagent.data.model

data class CartItem(
    val productId: String,
    val title: String,
    val category: String,
    val price: Double,
    val brand: String?,
    val subCategory: String?,
    val imageUrl: String?,
    val quantity: Int,
    val stock: Int?,
    val isActive: Boolean?,
    val unavailableReason: String?
) {
    val subtotal: Double
        get() = price * quantity
}

data class Cart(
    val conversationId: String,
    val items: List<CartItem>,
    val totalQuantity: Int,
    val totalPrice: Double,
    val messages: List<String>
) {
    companion object {
        fun empty(conversationId: String) = Cart(
            conversationId = conversationId,
            items = emptyList(),
            totalQuantity = 0,
            totalPrice = 0.0,
            messages = emptyList()
        )
    }
}
