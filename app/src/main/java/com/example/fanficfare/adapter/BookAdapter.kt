package com.example.fanficfare.adapter

import android.graphics.BitmapFactory
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.example.fanficfare.R
import com.example.fanficfare.model.BookItem

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
                card.context.getColor(com.example.fanficfare.R.color.fanficfare_primary)
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
                    imageCover.visibility = View.GONE
                    return
                }
            }
            imageCover.visibility = View.GONE
        }
    }

    fun isSelectionMode(): Boolean = selectionMode

    fun enterSelectionMode(book: BookItem) {
        selectionMode = true
        selectedIds.clear()
        selectedIds.add(book.uriString)
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
