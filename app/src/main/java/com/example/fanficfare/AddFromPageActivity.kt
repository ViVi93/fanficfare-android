package com.example.fanficfare

import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.button.MaterialButton
import com.google.android.material.checkbox.MaterialCheckBox
import com.google.android.material.textfield.TextInputEditText
import com.example.fanficfare.data.local.BookDao
import com.example.fanficfare.data.local.DownloadJobDao
import com.example.fanficfare.data.local.AppDatabase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File

class AddFromPageActivity : AppCompatActivity() {

    private lateinit var inputUrl: TextInputEditText
    private lateinit var checkNormalize: MaterialCheckBox
    private lateinit var buttonFetch: MaterialButton
    private lateinit var progressBar: ProgressBar
    private lateinit var textStatus: TextView
    private lateinit var textSeriesInfo: TextView
    private lateinit var recycler: RecyclerView
    private lateinit var textEmpty: TextView
    private lateinit var buttonSelectAll: MaterialButton
    private lateinit var buttonSelectNone: MaterialButton
    private lateinit var buttonDownloadSelected: MaterialButton

    private val adapter = StoryCheckAdapter()
    private var pythonBridge: com.example.fanficfare.PythonBridge? = null
    private var metadataJob: Job? = null
    private var fetchJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, true)
        setContentView(R.layout.activity_add_from_page)

        val toolbar = findViewById<androidx.appcompat.widget.Toolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        pythonBridge = com.example.fanficfare.PythonBridge(this)

        inputUrl = findViewById(R.id.inputUrl)
        checkNormalize = findViewById(R.id.checkNormalize)
        buttonFetch = findViewById(R.id.buttonFetch)
        progressBar = findViewById(R.id.progressBar)
        textStatus = findViewById(R.id.textStatus)
        textSeriesInfo = findViewById(R.id.textSeriesInfo)
        recycler = findViewById(R.id.recyclerStories)
        textEmpty = findViewById(R.id.textEmpty)
        buttonSelectAll = findViewById(R.id.buttonSelectAll)
        buttonSelectNone = findViewById(R.id.buttonSelectNone)
        buttonDownloadSelected = findViewById(R.id.buttonDownloadSelected)

        recycler.layoutManager = LinearLayoutManager(this)
        recycler.adapter = adapter

        val shared = intent?.getStringExtra(Intent.EXTRA_TEXT)?.trim().orEmpty()
        if (shared.isNotBlank()) {
            inputUrl.setText(shared)
        }

        buttonFetch.setOnClickListener {
            val url = inputUrl.text.toString().trim()
            if (url.isBlank()) {
                toast("Enter a page URL")
                return@setOnClickListener
            }
            fetchStoryList(url, checkNormalize.isChecked)
        }

        buttonSelectAll.setOnClickListener {
            val updated = adapter.currentList.map { it.copy(checked = true) }
            adapter.submitList(updated)
        }

        buttonSelectNone.setOnClickListener {
            val updated = adapter.currentList.map { it.copy(checked = false) }
            adapter.submitList(updated)
        }

        buttonDownloadSelected.setOnClickListener {
            downloadSelected()
        }

        updateActions()
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }

    override fun onDestroy() {
        super.onDestroy()
        fetchJob?.cancel()
        metadataJob?.cancel()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString("page_url", inputUrl.text.toString())
        outState.putBoolean("normalize", checkNormalize.isChecked)
        outState.putString("series_info", textSeriesInfo.text.toString())
        outState.putString("status", textStatus.text.toString())
        outState.putParcelableArrayList("items", ArrayList(adapter.currentList.map { it.toParcelable() }))
    }

    override fun onRestoreInstanceState(savedInstanceState: Bundle) {
        super.onRestoreInstanceState(savedInstanceState)
        inputUrl.setText(savedInstanceState.getString("page_url", ""))
        checkNormalize.isChecked = savedInstanceState.getBoolean("normalize", false)
        textSeriesInfo.text = savedInstanceState.getString("series_info", "")
        textSeriesInfo.visibility = if (textSeriesInfo.text.isBlank()) View.GONE else View.VISIBLE
        textStatus.text = savedInstanceState.getString("status", "")
        textStatus.visibility = if (textStatus.text.isBlank()) View.GONE else View.VISIBLE
        val saved = savedInstanceState.getParcelableArrayList<StoryItemParcel>("items")
        if (saved != null) {
            adapter.submitList(saved.map { it.toStoryItem() })
        }
        updateActions()
    }

    private fun fetchStoryList(pageUrl: String, normalize: Boolean) {
        fetchJob?.cancel()
        metadataJob?.cancel()
        adapter.submitList(emptyList())
        textSeriesInfo.visibility = View.GONE
        textSeriesInfo.text = ""
        setLoading(true)
        textStatus.visibility = View.VISIBLE
        textStatus.text = "Fetching stories..."

        val preFlight = runPreFlight(pageUrl)
        if (preFlight != null) {
            textStatus.text = preFlight
            textStatus.visibility = View.VISIBLE
        }

        fetchJob = lifecycleScope.launch {
            val raw = withContext(Dispatchers.IO) {
                pythonBridge?.listStoryUrls(pageUrl, normalize)
                    ?: """{"ok":false,"error":"Bridge missing"}"""
            }
            val result = safeJson(raw)
            setLoading(false)
            if (result == null || !result.optBoolean("ok")) {
                val error = result?.optString("error") ?: "Unknown error"
                textStatus.text = "Failed: $error"
                textStatus.visibility = View.VISIBLE
                return@launch
            }

            val urls = jsonStringList(result, "urllist")
            val seriesName = result.optString("name").ifBlank { null }
            val seriesDesc = result.optString("desc").ifBlank { null }

            if (urls.isEmpty()) {
                textStatus.text = "No story URLs found on this page"
                textStatus.visibility = View.VISIBLE
                adapter.submitList(emptyList())
                updateActions()
                return@launch
            }

            if (seriesName != null) {
                textSeriesInfo.text = "Series: $seriesName"
                textSeriesInfo.visibility = View.VISIBLE
            } else {
                textSeriesInfo.visibility = View.GONE
            }

            textStatus.text = "Found ${urls.size} stories"
            textStatus.visibility = View.VISIBLE

            val items = urls.map { url -> StoryItem(url = url) }
            adapter.submitList(items)
            updateActions()

            if (!seriesDesc.isNullOrBlank()) {
                AlertDialog.Builder(this@AddFromPageActivity)
                    .setTitle(seriesName ?: "Series")
                    .setMessage(seriesDesc)
                    .setPositiveButton("OK", null)
                    .show()
            }

            startLazyMetadata(items)
        }
    }

    private fun startLazyMetadata(items: List<StoryItem>) {
        metadataJob?.cancel()
        if (items.isEmpty()) return
        textStatus.text = "Fetching metadata..."

        metadataJob = lifecycleScope.launch {
            val updated = items.toMutableList()
            for (i in updated.indices) {
                val metaRaw = withContext(Dispatchers.IO) {
                    pythonBridge?.fanficfareMetadata(updated[i].url)
                        ?: """{"ok":false}"""
                }
                val meta = safeJson(metaRaw)
                if (meta != null && meta.optBoolean("ok")) {
                    updated[i] = updated[i].copy(
                        title = meta.optString("title").ifBlank { updated[i].url },
                        chapters = meta.optInt("chapters", 0)
                    )
                } else {
                    updated[i] = updated[i].copy(title = updated[i].url)
                }
                adapter.submitList(updated.toList())
            }
            val successCount = updated.count { it.title != it.url }
            textStatus.text = "Ready: $successCount/${updated.size} resolved"
            updateActions()
        }
    }

    private fun downloadSelected() {
        val selected = adapter.currentList.filter { it.checked }
        if (selected.isEmpty()) {
            toast("No stories selected")
            return
        }
        textStatus.visibility = View.VISIBLE
        textStatus.text = "Enqueuing ${selected.size} downloads..."
        setFetchEnabled(false)

        lifecycleScope.launch {
            var success = 0
            var fail = 0
            for (item in selected) {
                try {
                    withContext(Dispatchers.IO) {
                        BookRepository(this@AddFromPageActivity).enqueueDownload(item.url)
                    }
                    success++
                } catch (e: Exception) {
                    Log.w("AddFromPage", "enqueue failed", e)
                    fail++
                }
            }
            textStatus.text = "Enqueued: $success, failed: $fail"
            setFetchEnabled(true)
            toast("Enqueued $success, failed $fail")
        }
    }

    private fun runPreFlight(pageUrl: String): String? {
        try {
            val raw = pythonBridge?.getLoginStatus(pageUrl) ?: return null
            val status = safeJson(raw)
            if (status == null) return null
            val usernamePresent = status.optBoolean("username_present", false)
            val passwordPresent = status.optBoolean("password_present", false)
            val site = status.optString("site").ifBlank { null }
            return if ((usernamePresent && passwordPresent).not() && site != null) {
                "Warning: $site may require configured credentials."
            } else null
        } catch (e: Exception) {
            return null
        }
    }

    private fun setLoading(loading: Boolean) {
        progressBar.visibility = if (loading) View.VISIBLE else View.GONE
        setFetchEnabled(!loading)
    }

    private fun setFetchEnabled(enabled: Boolean) {
        buttonFetch.isEnabled = enabled
        inputUrl.isEnabled = enabled
        checkNormalize.isEnabled = enabled
    }

    private fun updateActions() {
        val hasItems = adapter.itemCount > 0
        textEmpty.visibility = if (hasItems) View.GONE else View.VISIBLE
        val selectionBar = findViewById<View>(R.id.selectionBar)
        selectionBar.visibility = if (hasItems) View.VISIBLE else View.GONE
        buttonSelectAll.visibility = View.VISIBLE
        buttonSelectNone.visibility = View.VISIBLE
        buttonDownloadSelected.visibility = View.VISIBLE
    }

    private fun safeJson(raw: String?): JSONObject? {
        if (raw.isNullOrBlank()) return null
        return try {
            JSONObject(raw)
        } catch (e: Exception) {
            null
        }
    }

    private fun jsonStringList(obj: JSONObject, key: String): List<String> {
        val arr = obj.optJSONArray(key)
        return if (arr != null) {
            List(arr.length()) { i -> arr.optString(i).orEmpty().trim() }.filter { it.isNotBlank() }
        } else {
            val raw = obj.optString(key).orEmpty().trim()
            if (raw.isBlank()) emptyList() else raw.lines().map { it.trim() }.filter { it.isNotBlank() }
        }
    }

    private fun toast(text: String) {
        android.widget.Toast.makeText(this, text, android.widget.Toast.LENGTH_LONG).show()
    }

    private data class StoryItem(
        val url: String,
        var title: String = "",
        var chapters: Int = 0,
        var checked: Boolean = true
    ) {
        fun toParcelable(): StoryItemParcel = StoryItemParcel(url, title, chapters, checked)
    }

    private class StoryItemParcel(
        val url: String,
        val title: String,
        val chapters: Int,
        val checked: Boolean
    ) : android.os.Parcelable {
        fun toStoryItem(): AddFromPageActivity.StoryItem =
            AddFromPageActivity.StoryItem(url, title, chapters, checked)

        override fun describeContents(): Int = 0
        override fun writeToParcel(dest: android.os.Parcel, flags: Int) {
            dest.writeString(url)
            dest.writeString(title)
            dest.writeInt(chapters)
            dest.writeByte(if (checked) 1 else 0)
        }

        companion object {
            @JvmField
            val CREATOR = object : android.os.Parcelable.Creator<StoryItemParcel> {
                override fun createFromParcel(source: android.os.Parcel): StoryItemParcel =
                    StoryItemParcel(
                        url = source.readString().orEmpty(),
                        title = source.readString().orEmpty(),
                        chapters = source.readInt(),
                        checked = source.readByte() != 0.toByte()
                    )

                override fun newArray(size: Int): Array<StoryItemParcel?> = arrayOfNulls(size)
            }
        }
    }

    private inner class StoryCheckAdapter :
        RecyclerView.Adapter<StoryCheckAdapter.StoryVH>() {

        private val items = mutableListOf<StoryItem>()

        fun submitList(newItems: List<StoryItem>) {
            items.clear()
            items.addAll(newItems)
            notifyDataSetChanged()
        }

        val currentList: List<StoryItem> get() = items

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): StoryVH {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.row_story_item, parent, false)
            return StoryVH(view)
        }

        override fun getItemCount(): Int = items.size

        override fun onBindViewHolder(holder: StoryVH, position: Int) {
            holder.bind(items[position])
        }

        inner class StoryVH(itemView: View) : RecyclerView.ViewHolder(itemView) {
            private val checkSelected = itemView.findViewById<MaterialCheckBox>(R.id.checkSelected)
            private val textTitle = itemView.findViewById<TextView>(R.id.textTitle)
            private val textMeta = itemView.findViewById<TextView>(R.id.textMeta)

            fun bind(item: StoryItem) {
                textTitle.text = if (item.title.isNotBlank()) item.title else item.url
                textMeta.text = if (item.chapters > 0) "${item.chapters} chapters" else item.url
                checkSelected.isChecked = item.checked
                itemView.setOnClickListener {
                    val newChecked = !item.checked
                    item.checked = newChecked
                    checkSelected.isChecked = newChecked
                }
                checkSelected.setOnClickListener {
                    item.checked = checkSelected.isChecked
                }
            }
        }
    }
}
