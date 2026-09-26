package com.vivi.aharana.util

import android.graphics.Color

object CoverColorUtils {

    private val materialColors = intArrayOf(
        0xFF1B5E20.toInt(), // Dark Green
        0xFF0D47A1.toInt(), // Dark Blue
        0xFF4A148C.toInt(), // Dark Purple
        0xFFB71C1C.toInt(), // Dark Red
        0xFFE65100.toInt(), // Dark Orange
        0xFF006064.toInt(), // Dark Teal
        0xFF33691E.toInt(), // Dark Light Green
        0xFF263238.toInt(), // Dark Blue Grey
        0xFF3E2723.toInt(), // Dark Brown
        0xFF01579B.toInt(), // Dark Light Blue
        0xFF4527A0.toInt(), // Dark Deep Purple
        0xFF880E4F.toInt(), // Dark Pink
    )

    /**
     * Generate a consistent color from a string (e.g., book title).
     * Uses a simple hash to pick from a curated Material Design dark palette.
     */
    fun colorFromString(input: String): Int {
        var hash = 0
        for (i in 0 until input.length) {
            hash = 31 * hash + input.codePointAt(i)
        }
        return materialColors[Math.abs(hash) % materialColors.size]
    }

    /**
     * Generate a contrasting text color (white or black) for the given background color.
     */
    fun contrastingTextColor(backgroundColor: Int): Int {
        val r = Color.red(backgroundColor)
        val g = Color.green(backgroundColor)
        val b = Color.blue(backgroundColor)
        // Calculate relative luminance
        val luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return if (luminance > 0.5) Color.BLACK else Color.WHITE
    }

    /**
     * Get first letter initials from title/author for placeholder text.
     */
    fun initialsFromTitle(title: String, author: String): String {
        val titleInitial = title.trim().take(1).uppercase()
        val authorInitial = author.trim().take(1).uppercase()
        return if (titleInitial.isNotBlank() && authorInitial.isNotBlank()) {
            "$titleInitial$authorInitial"
        } else if (titleInitial.isNotBlank()) {
            titleInitial
        } else {
            "?"
        }
    }
}