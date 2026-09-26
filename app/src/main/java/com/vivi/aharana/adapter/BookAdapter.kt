package com.vivi.aharana.adapter

import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.vivi.aharana.R
import com.vivi.aharana.model.BookItem
import com.vivi.aharana.util.CoverColorUtils

class BookAdapter(
    private val books: List<BookItem>,
    private val onBookClicked: (BookItem) -> Unit,
    private val onBookLongClicked: (BookItem) -> Unit
) : RecyclerView.Adapter<BookAdapter.BookViewHolder>() {

    private val selectedIds = mutableSetOf<String>()
    var selectionMode = false
        private set

    inner class BookViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val textTitle: TextView = itemView.findViewById(R.id.textTitle)
        private val textAuthor: TextView = itemView.findViewById(R.id.textAuthor)
        private val imageCover: ImageView = itemView.findViewById(R.id.imageCover)
        private val textChapters: TextView = itemView.findViewById(R.id.textChapters)

        fun bind(book: BookItem) {
            textTitle.text = book.title.ifBlank { "Untitled" }
            textAuthor.text = book.author.ifBlank { "Unknown author" }
            textChapters.text = if (book.chapters > 0) "${book.chapters} chapters" else ""
            val selected = selectedIds.contains(book.uriString)
            itemView.isSelected = selected
            val card = itemView as com.google.android.material.card.MaterialCardView
            val res = card.context.resources
            val strokeColor = if (selected) {
                card.context.getColor(com.vivi.aharana.R.color.fanficfare_primary)
            } else {
                card.context.getColor(android.R.color.transparent)
            }
            val strokeWidth = if (selected) res.getDimensionPixelSize(R.dimen.selection_stroke) else 0
            card.strokeColor = strokeColor
            card.strokeWidth = strokeWidth
            itemView.setOnClickListener {
                if (selectionMode) {
                    toggleSelection(book)
                } else {
                    onBookClicked(book)
                }
            }
            itemView.setOnLongClickListener {
                onBookLongClicked(book)
                true
            }

            // Set dynamic content description for accessibility
            imageCover.contentDescription = "Cover for ${book.title} by ${book.author}"

            val cover = book.coverUriString
            if (cover?.isNotBlank() == true && cover.startsWith("data:")) {
                try {
                    val comma = cover.indexOf(",")
                    if (comma > 0) {
                        val base64 = cover.substring(comma + 1)
                        val bytes = android.util.Base64.decode(base64, android.util.Base64.DEFAULT)
                        val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                        if (bitmap != null) {
                            imageCover.setImageBitmap(bitmap)
                            imageCover.visibility = View.VISIBLE
                            return
                        }
                    }
                } catch (e: Exception) {
                    android.util.Log.d("FFF-Cover", "decodeByteArray failed: type=" + e.javaClass.simpleName + " msg=" + (e.message ?: ""))
                }
            }
            // No cover data - generate placeholder
            showPlaceholder(book)
        }

        private fun showPlaceholder(book: BookItem) {
            val bgColor = CoverColorUtils.colorFromString(book.title)
            val textColor = CoverColorUtils.contrastingTextColor(bgColor)
            val initials = CoverColorUtils.initialsFromTitle(book.title, book.author)

            val width = imageCover.width
            val height = imageCover.height
            if (width <= 0 || height <= 0) {
                imageCover.post {
                    if (imageCover.width > 0 && imageCover.height > 0) showPlaceholder(book)
                }
                return
            }
            val insetPx = (3 * imageCover.resources.displayMetrics.density).toInt()
            val bitmap = android.graphics.Bitmap.createBitmap(width, height, android.graphics.Bitmap.Config.ARGB_8888)
            val canvas = Canvas(bitmap)
            val paint = Paint().apply {
                isAntiAlias = true
                color = bgColor
                style = Paint.Style.FILL
            }
            canvas.drawRect(
                insetPx.toFloat(),
                insetPx.toFloat(),
                (width - insetPx).toFloat(),
                (height - insetPx).toFloat(),
                paint
            )

            val textPaint = Paint().apply {
                isAntiAlias = true
                color = textColor
                textSize = (minOf(width, height) * 0.38f)
                typeface = Typeface.DEFAULT_BOLD
                textAlign = Paint.Align.CENTER
            }
            val bounds = android.graphics.Rect()
            textPaint.getTextBounds(initials, 0, initials.length, bounds)
            canvas.drawText(
                initials,
                width / 2f,
                height / 2f + bounds.height() / 2f - bounds.bottom,
                textPaint
            )
            imageCover.setImageBitmap(bitmap)
            imageCover.visibility = View.VISIBLE
        }
    }

    fun isSelectionMode(): Boolean = selectionMode

    fun enterSelectionMode(book: BookItem) {
        selectionMode = true
        selectedIds.clear()
        selectedIds.add(book.uriString)
        notifyDataSetChanged()
    }

    /** Enter selection mode with nothing selected, so the user picks the books. */
    fun enterSelectionMode() {
        selectionMode = true
        selectedIds.clear()
        notifyDataSetChanged()
    }

    fun toggleSelection(book: BookItem) {
        if (selectedIds.contains(book.uriString)) {
            selectedIds.remove(book.uriString)
        } else {
            selectedIds.add(book.uriString)
        }
        if (selectedIds.isEmpty()) {
            selectionMode = false
        }
        notifyDataSetChanged()
    }

    fun clearSelection() {
        selectionMode = false
        selectedIds.clear()
        notifyDataSetChanged()
    }

    fun getSelectedBooks(): List<BookItem> = books.filter { selectedIds.contains(it.uriString) }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): BookViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_book, parent, false)
        return BookViewHolder(view)
    }

    override fun onBindViewHolder(holder: BookViewHolder, position: Int) {
        holder.bind(books[position])
    }

    override fun getItemCount(): Int = books.size
}
