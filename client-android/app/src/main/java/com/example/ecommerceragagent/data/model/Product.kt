package com.example.ecommerceragagent.data.model

data class Product(
    val productId: String,
    val title: String,
    val category: String,
    val price: Double,
    val brand: String?,
    val subCategory: String?,
    val imageUrl: String?
)
