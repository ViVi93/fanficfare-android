package com.example.fanficfare

import android.os.Bundle
import android.view.View
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.fanficfare.adapter.BookAdapter
import com.example.fanficfare.model.BookItem
import org.json.JSONObject

class MainActivity : AppCompatActivity() {

    private val downloads = mutableListOf<BookItem>()
    private lateinit var bookAdapter: BookAdapter
    private val bridge = PythonBridge()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        bookAdapter = BookAdapter(downloads) { book ->
            findViewById<TextView>(R.id.textStatus).text = "Selected: ${book.title}"
        }
        findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.bookList).layoutManager = LinearLayoutManager(this)
        findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.bookList).adapter = bookAdapter

        findViewById<androidx.appcompat.widget.Toolbar>(R.id.toolbar).setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.action_download -> {
                    showDownloadDialog()
                    true
                }
                R.id.action_update -> {
                    showUpdateDialog()
                    true
                }
                else -> false
            }
        }
    }

    private fun setStatus(text: String) {
        findViewById<TextView>(R.id.textStatus).text = text
    }

    private fun showDownloadDialog() {
        val view = layoutInflater.inflate(R.layout.dialog_download, null)
        val input = view.findViewById<EditText>(R.id.inputUrl)
        view.findViewById<android.widget.Button>(R.id.buttonDownload).setOnClickListener {
            val url = input.text.toString().trim()
            if (url.isBlank()) return@setOnClickListener
            setStatus("Downloading...")
            Thread {
                val resultJson = bridge.fanficfareDownload(url, filesDir.absolutePath)
                val result = json(resultJson)
                runOnUiThread {
                    if (result?.optBoolean("ok") == true) {
                        val title = result.optString("title", "story")
                        setStatus("Saved: $title")
                    } else {
                        setStatus("Download failed: ${result?.optString("error") ?: "unknown"}")
                    }
                }
            }.start()
        }
        view.findViewById<android.widget.Button>(R.id.buttonUpdate).setOnClickListener {
            val url = input.text.toString().trim()
            if (url.isBlank()) return@setOnClickListener
            setStatus("Updating...")
            Thread {
                val resultJson = bridge.fanficfareMetadata(url)
                val result = json(resultJson)
                runOnUiThread {
                    setStatus(if (result?.optBoolean("ok") == true) "Metadata fetched" else "Update check failed")
                }
            }.start()
        }
        android.app.AlertDialog.Builder(this)
            .setTitle("FanFicFare")
            .setView(view)
            .setNegativeButton("Close", null)
            .show()
    }

    private fun showUpdateDialog() {
        val input = EditText(this)
        input.hint = "Story URL"
        android.app.AlertDialog.Builder(this)
            .setTitle("Update EPUB")
            .setView(input)
            .setPositiveButton("Update") { _, _ ->
                val url = input.text.toString().trim()
                if (url.isBlank()) return@setPositiveButton
                setStatus("Updating...")
                Thread {
                    val resultJson = bridge.fanficfareMetadata(url)
                    val result = json(resultJson)
                    runOnUiThread {
                        setStatus(if (result?.optBoolean("ok") == true) "Update check done" else "Update failed")
                    }
                }.start()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun json(text: String): JSONObject? {
        return try { JSONObject(text) } catch (e: Exception) { null }
    }
}
