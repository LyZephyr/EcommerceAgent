package com.example.ecommerceragagent.data.model

data class CompareProduct(
    val productId: String,
    val title: String
)

data class CompareRow(
    val dimension: String,
    val values: Map<String, String>
)

data class CompareTable(
    val products: List<CompareProduct>,
    val rows: List<CompareRow>
)
