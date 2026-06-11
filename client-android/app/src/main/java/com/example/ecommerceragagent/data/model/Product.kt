package com.example.ecommerceragagent.data.model

data class Product(
    val productId: String,
    val title: String,
    val category: String,
    val price: Double,
    val brand: String?,
    val subCategory: String?,
    val imageUrl: String?,
    val stock: Int? = null,
    val detailUrl: String? = null,
    val landingUrl: String? = null,
    val highlights: List<String> = emptyList(),
    val stockStatus: String? = null,
    val unavailableReason: String? = null,
    val groupLabel: String? = null
)

data class ProductSpec(
    val name: String,
    val value: String
)

data class ProductFaq(
    val question: String,
    val answer: String
)

data class ReviewSummary(
    val averageRating: Double?,
    val totalCount: Int?,
    val highlights: List<String>
)

data class ProductDetail(
    val product: Product,
    val description: String?,
    val specs: List<ProductSpec>,
    val faq: List<ProductFaq>,
    val reviewSummary: ReviewSummary?
)
