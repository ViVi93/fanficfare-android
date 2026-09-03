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
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.example.fanficfare.ViewModelFactory
import com.google.android.material.button.MaterialButton
import com.google.android.material.checkbox.MaterialCheckBox
import com.google.android.material.textfield.TextInputEditText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import kotlinx.coroutines.delay

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
    private lateinit var viewModel: LibraryViewModel

    override fun onCreate(savedInstanceState: Bundle?) {
        DiagnosticLog.append(this, "AddFromPage", "onCreate intent=${intent?.action}")
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, true)
        setContentView(R.layout.activity_add_from_page)

        val toolbar = findViewById<androidx.appcompat.widget.Toolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        if (!com.chaquo.python.Python.isStarted()) {
            try {
                com.chaquo.python.Python.start(com.chaquo.python.android.AndroidPlatform(this))
            } catch (e: Exception) {
                DiagnosticLog.append(this, "AddFromPage", "python_start_failed=${e.message}")
            }
        }

        pythonBridge = com.example.fanficfare.PythonBridge(this)
        pythonBridge?.initialize(com.example.fanficfare.SettingsActivity.getConfigDir(this).absolutePath)

        val repository = BookRepository(this)
        viewModel = ViewModelProvider(this, ViewModelFactory(repository))[LibraryViewModel::class.java]

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

        val persisted = loadPersistedAddFromPageItems()
        if (persisted != null) {
            val (pageUrl, normalize, items) = persisted
            inputUrl.setText(pageUrl)
            checkNormalize.isChecked = normalize
            adapter.submitList(items)
            updateActions()
            if (items.any { it.title.isBlank() }) {
                startLazyMetadata(items)
            }
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

    override fun onCreateOptionsMenu(menu: android.view.Menu?): Boolean {
        menuInflater.inflate(R.menu.add_from_page_menu, menu)
        return true
    }

    override fun onOptionsItemSelected(item: android.view.MenuItem): Boolean {
        return when (item.itemId) {
            R.id.action_cancel_metadata -> {
                cancelMetadataFetch()
                true
            }
            R.id.action_clear_saved -> {
                clearPersistedAddFromPageItems()
                toast("Cleared saved entries")
                true
            }
            else -> super.onOptionsItemSelected(item)
        }
    }

    private fun cancelMetadataFetch() {
        metadataJob?.cancel()
        metadataJob = null
        try {
            androidx.work.WorkManager.getInstance(this)
                .cancelAllWorkByTag("fanficfare_metadata")
        } catch (e: Exception) {
            android.util.Log.e("AddFromPage", "cancel_metadata_failed", e)
        }
        textStatus.text = "Ready"
        try {
            val repository = BookRepository(this)
            kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.Dispatchers.IO).launch {
                try {
                    val now = System.currentTimeMillis()
                    repository.getAllDownloadJobs()
                        .filter { it.type == "metadata" && setOf("running", "queued").contains(it.status) }
                        .forEach { job ->
                            repository.updateDownloadJobStatus(job.id, "cancelled", now)
                        }
                } catch (e: Exception) {
                    android.util.Log.e("AddFromPage", "cancel_metadata_db_update_failed", e)
                }
            }
        } catch (e: Exception) {
            android.util.Log.e("AddFromPage", "cancel_metadata_scope_failed", e)
        }
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }

    override fun onStart() {
        super.onStart()
        DiagnosticLog.append(this, "AddFromPage", "onStart")
    }

    override fun onResume() {
        super.onResume()
        DiagnosticLog.append(this, "AddFromPage", "onResume")
    }

    override fun onPause() {
        super.onPause()
        DiagnosticLog.append(this, "AddFromPage", "onPause isFinishing=${isFinishing}")
    }

    override fun onStop() {
        super.onStop()
        DiagnosticLog.append(this, "AddFromPage", "onStop isFinishing=${isFinishing}")
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
            persistAddFromPageItems(pageUrl, normalize, items)
            updateActions()

            if (!seriesDesc.isNullOrBlank()) {
                AlertDialog.Builder(this@AddFromPageActivity)
                    .setTitle(seriesName ?: "Series")
                    .setMessage(seriesDesc)
                    .setPositiveButton("OK", null)
                    .show()
            }
        }
    }

    private fun startLazyMetadata(items: List<StoryItem>) {
        metadataJob?.cancel()
        if (items.isEmpty()) return
        textStatus.text = "Fetching metadata..."

        val urlToIndex = items.withIndex().associate { it.value.url to it.index }
        val updated = items.toMutableList()
        var remaining = updated.indices.toMutableSet()
        DiagnosticLog.append(this, "AddFromPage", "startLazyMetadata urlCount=${urlToIndex.size}")

        fun applyMeta(idx: Int, meta: JSONObject?) {
            if (meta != null && meta.optBoolean("ok")) {
                updated[idx] = updated[idx].copy(
                    title = meta.optString("title").ifBlank { updated[idx].url },
                    chapters = meta.optInt("chapters", 0)
                )
            } else {
                updated[idx] = updated[idx].copy(title = updated[idx].url)
            }
            adapter.submitList(updated.toList())
            remaining.remove(idx)
        }

        fun markComplete() {
            val successCount = updated.count { it.title != it.url }
            DiagnosticLog.append(this, "AddFromPage", "observer_complete successCount=$successCount total=${updated.size}")
            textStatus.text = "Ready: $successCount/${updated.size} resolved"
            updateActions()
        }

        metadataJob = lifecycleScope.launch {
            try {
                val existingJobs = withContext(Dispatchers.IO) { BookRepository(this@AddFromPageActivity).getAllDownloadJobs() }
                val initialLatestByUrl = existingJobs.filter { entity ->
                    entity.type == "metadata" && !entity.inputUrl.isNullOrBlank() &&
                            setOf("success", "failed", "cancelled").contains(entity.status)
                }.groupBy { it.inputUrl!! }.mapValues { entry -> entry.value.maxByOrNull { it.createdAt }!! }
                val processedUrls = mutableSetOf<String>()
                for ((url, entity) in initialLatestByUrl) {
                    val idx = urlToIndex[url] ?: continue
                    if (!remaining.contains(idx)) continue
                    processedUrls.add(url)
                    val meta = if (entity.status == "success" && !entity.resultJson.isNullOrBlank()) safeJson(entity.resultJson) else null
                    applyMeta(idx, meta)
                    DiagnosticLog.append(this@AddFromPageActivity, "AddFromPage", "backfill_entity url=$url status=${entity.status}")
                }
                if (remaining.isEmpty()) {
                    markComplete()
                    return@launch
                }

                viewModel.latestJobs.observe(this@AddFromPageActivity,
                    androidx.lifecycle.Observer { jobs ->
                        if (remaining.isEmpty()) return@Observer
                        val latestByUrl = jobs.filter { entity ->
                            entity.type == "metadata" && !entity.inputUrl.isNullOrBlank() &&
                                    setOf("success", "failed", "cancelled").contains(entity.status)
                        }.groupBy { it.inputUrl!! }.mapValues { entry -> entry.value.maxByOrNull { it.createdAt }!! }
                        var metadataSeen = 0
                        for ((url, entity) in latestByUrl) {
                            val idx = urlToIndex[url] ?: continue
                            if (!remaining.contains(idx)) continue
                            if (!processedUrls.add(url)) continue
                            metadataSeen++
                            DiagnosticLog.append(this@AddFromPageActivity, "AddFromPage", "observer_entity url=$url status=${entity.status}")
                            val meta = if (entity.status == "success" && !entity.resultJson.isNullOrBlank()) safeJson(entity.resultJson) else null
                            applyMeta(idx, meta)
                        }
                        DiagnosticLog.append(this@AddFromPageActivity, "AddFromPage", "observer_update metadataSeen=$metadataSeen remaining=${remaining.size}")
                        if (remaining.isEmpty()) {
                            markComplete()
                            metadataJob?.cancel()
                        }
                    })

                for (url in urlToIndex.keys) {
                    if (processedUrls.contains(url)) continue
                    if (remaining.isEmpty()) break
                    try {
                        withContext(Dispatchers.IO) {
                            BookRepository(this@AddFromPageActivity).enqueueMetadata(url)
                        }
                        DiagnosticLog.append(this@AddFromPageActivity, "AddFromPage", "enqueued_metadata url=$url")
                    } catch (e: Exception) {
                        Log.w("AddFromPage", "enqueueMetadata failed", e)
                        DiagnosticLog.append(this@AddFromPageActivity, "AddFromPage", "enqueue_failed url=$url error=${e.message}")
                        val idx = urlToIndex[url]
                        if (idx != null) {
                            applyMeta(idx, null)
                        }
                    }
                }
                DiagnosticLog.append(this@AddFromPageActivity, "AddFromPage", "enqueue_complete remaining=${remaining.size}")
                if (remaining.isEmpty()) markComplete()
            } catch (e: Exception) {
                Log.e("AddFromPage", "loop_failed", e)
                DiagnosticLog.append(this@AddFromPageActivity, "AddFromPage", "loop_failed | exception=${e.javaClass.simpleName} | msg=${e.message}")
            }
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

    private fun addFromPageFile(): File = File(getAddFromPageDir(), "add_from_page_items.json")

    private fun persistAddFromPageItems(pageUrl: String, normalize: Boolean, items: List<StoryItem>) {
        try {
            val root = JSONObject()
            root.put("pageUrl", pageUrl)
            root.put("normalize", normalize)
            val arr = JSONArray()
            for (item in items) {
                val obj = JSONObject()
                obj.put("url", item.url)
                obj.put("title", item.title)
                obj.put("chapters", item.chapters)
                obj.put("checked", item.checked)
                arr.put(obj)
            }
            root.put("items", arr)
            addFromPageFile().writeText(root.toString())
            DiagnosticLog.append(this, "AddFromPage", "persist_items pageUrl=$pageUrl count=${items.size}")
        } catch (e: Exception) {
            DiagnosticLog.appendException(this, "AddFromPage", "persist_items_failed", e)
        }
    }

    private fun loadPersistedAddFromPageItems(): Triple<String, Boolean, List<StoryItem>>? {
        return try {
            val file = addFromPageFile()
            if (!file.exists()) return null
            val root = JSONObject(file.readText())
            val pageUrl = root.optString("pageUrl", "").trim()
            if (pageUrl.isBlank()) return null
            val normalize = root.optBoolean("normalize", false)
            val arr = root.optJSONArray("items") ?: return null
            val items = mutableListOf<StoryItem>()
            for (i in 0 until arr.length()) {
                val obj = arr.optJSONObject(i) ?: continue
                val url = obj.optString("url", "").trim()
                if (url.isBlank()) continue
                items.add(
                    StoryItem(
                        url = url,
                        title = obj.optString("title", ""),
                        chapters = obj.optInt("chapters", 0),
                        checked = obj.optBoolean("checked", true)
                    )
                )
            }
            if (items.isEmpty()) return null
            DiagnosticLog.append(this, "AddFromPage", "load_persisted_items pageUrl=$pageUrl count=${items.size}")
            Triple(pageUrl, normalize, items)
        } catch (e: Exception) {
            DiagnosticLog.appendException(this, "AddFromPage", "load_persisted_items_failed", e)
            null
        }
    }

    private fun clearPersistedAddFromPageItems() {
        try {
            val file = addFromPageFile()
            if (file.exists()) file.delete()
            DiagnosticLog.append(this, "AddFromPage", "clear_persisted_items")
        } catch (e: Exception) {
            DiagnosticLog.appendException(this, "AddFromPage", "clear_persisted_items_failed", e)
        }
    }

    private fun getAddFromPageDir(): File {
        val dir = File(filesDir, "add_from_page")
        if (!dir.exists()) dir.mkdirs()
        return dir
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
