package com.example.fanficfare.adapter

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
    private val onBookClicked: (BookItem) -> Unit
) : RecyclerView.Adapter<BookAdapter.BookViewHolder>() {

    inner class BookViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val textTitle: TextView = itemView.findViewById(R.id.textTitle)
        private val textAuthor: TextView = itemView.findViewById(R.id.textAuthor)
        private val imageCover: ImageView = itemView.findViewById(R.id.imageCover)

        fun bind(book: BookItem) {
            textTitle.text = book.title.ifBlank { "Untitled" }
            textAuthor.text = book.author.ifBlank { "Unknown author" }
            imageCover.visibility = View.GONE
            itemView.setOnClickListener { onBookClicked(book) }
        }
    }

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
