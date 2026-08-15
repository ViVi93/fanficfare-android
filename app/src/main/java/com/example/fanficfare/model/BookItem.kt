package com.example.fanficfare.model

data class BookItem(
    val title: String,
    val author: String,
    val uriString: String,
    val lastModified: Long,
    val sizeBytes: Long,
    val coverUriString: String? = null
)
