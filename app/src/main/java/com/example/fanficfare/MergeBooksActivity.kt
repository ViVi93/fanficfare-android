package com.example.fanficfare

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.ImageButton
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.workDataOf
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/**
 * Confirms a library-level merge of several EPUBs into one book.
 *
 * Shows the selected books in order and lets them be reordered, because that
 * order is the order they will appear in the merged book. The first book is the
 * base: it supplies the merged book's cover and its metadata defaults. Nothing
 * is written here -- the work is handed to [MergeBooksWorker].
 */
class MergeBooksActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_PATHS = "merge_paths"
        const val EXTRA_TITLES = "merge_titles"
        const val EXTRA_AUTHORS = "merge_authors"
        const val EXTRA_COVERS = "merge_covers"
    }

    private class Source(
        val path: String,
        val title: String,
        val author: String,
        val cover: String,
        var chapters: Int = 0,
        var tocEntries: Int = 0,
        var sizeBytes: Long = 0L,
    )

    private val sources = mutableListOf<Source>()
    private lateinit var adapter: SourceAdapter
    private lateinit var summaryView: TextView
    private lateinit var warningsView: TextView
    private lateinit var titleField: EditText
    private lateinit var authorField: EditText
    private lateinit var progressBar: ProgressBar
    private lateinit var mergeButton: Button
    private lateinit var tocStyleGroup: android.widget.RadioGroup
    private lateinit var outputNameView: TextView
    private lateinit var shortenLabelsBox: android.widget.CheckBox
    private lateinit var renumberChaptersBox: android.widget.CheckBox

    private var workId: UUID? = null

    /** True once the style is settled, so a late preview cannot override it. */
    private var tocStyleChosen = false

    /** Same, for the chapter-name options. */
    private var labelsChosen = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Same window setup as the other activities, so content starts below the
        // status bar rather than underneath it.
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.VANILLA_ICE_CREAM) {
            androidx.core.view.WindowCompat.setDecorFitsSystemWindows(window, true)
        }
        setContentView(R.layout.activity_merge_books)
        supportActionBar?.title = getString(R.string.merge_title)

        collectSources()
        if (sources.size < 2) {
            toast(getString(R.string.merge_need_two))
            finish()
            return
        }

        summaryView = findViewById(R.id.mergeSummary)
        warningsView = findViewById(R.id.mergeWarnings)
        titleField = findViewById(R.id.mergeTitle)
        authorField = findViewById(R.id.mergeAuthor)
        progressBar = findViewById(R.id.mergeProgress)
        mergeButton = findViewById(R.id.mergeButton)
        mergeButton.setOnClickListener { startMerge() }

        tocStyleGroup = findViewById(R.id.mergeTocStyle)
        tocStyleGroup.setOnCheckedChangeListener { _, _ -> tocStyleChosen = true }
        shortenLabelsBox = findViewById(R.id.mergeShortenLabels)
        renumberChaptersBox = findViewById(R.id.mergeRenumberChapters)
        shortenLabelsBox.setOnCheckedChangeListener { _, _ -> labelsChosen = true }
        renumberChaptersBox.setOnCheckedChangeListener { _, _ -> labelsChosen = true }

        val list = findViewById<RecyclerView>(R.id.mergeSourceList)
        adapter = SourceAdapter()
        list.layoutManager = LinearLayoutManager(this)
        list.adapter = adapter

        titleField.setText(sources.first().title)
        authorField.setText(sources.first().author)

        outputNameView = findViewById(R.id.mergeOutputName)
        titleField.addTextChangedListener(object : android.text.TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) = Unit
            override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) =
                showOutputName(s?.toString().orEmpty())
            override fun afterTextChanged(s: android.text.Editable?) = Unit
        })
        showOutputName(sources.first().title)
        loadPreview()
    }

    private fun collectSources() {
        val paths = intent.getStringArrayListExtra(EXTRA_PATHS).orEmpty()
        val titles = intent.getStringArrayListExtra(EXTRA_TITLES).orEmpty()
        val authors = intent.getStringArrayListExtra(EXTRA_AUTHORS).orEmpty()
        val covers = intent.getStringArrayListExtra(EXTRA_COVERS).orEmpty()
        for (index in paths.indices) {
            sources.add(
                Source(
                    path = paths[index],
                    title = titles.getOrElse(index) { "" }
                        .ifBlank { paths[index].substringAfterLast('/') },
                    author = authors.getOrElse(index) { "" },
                    cover = covers.getOrElse(index) { "" },
                )
            )
        }
    }

    /** Ask Python what the merge would produce. The UI stays usable meanwhile. */
    private fun loadPreview() {
        progressBar.visibility = View.VISIBLE
        lifecycleScope.launch {
            val payload = JSONArray(sources.map { it.path }).toString()
            val raw = withContext(Dispatchers.IO) {
                PythonBridge(applicationContext).mergeBooksPreview(payload)
            }
            progressBar.visibility = View.GONE
            val result = try {
                JSONObject(raw)
            } catch (e: Exception) {
                null
            }
            if (result == null || !result.optBoolean("ok", false)) {
                summaryView.text = result?.optString("error")
                    ?: getString(R.string.merge_preview_failed)
                return@launch
            }
            val previews = result.optJSONArray("sources") ?: JSONArray()
            for (index in 0 until minOf(previews.length(), sources.size)) {
                val item = previews.getJSONObject(index)
                sources[index].chapters = item.optInt("chapters", 0)
                sources[index].tocEntries = item.optInt("toc_entries", 0)
                sources[index].sizeBytes = item.optLong("size_bytes", 0L)
            }
            adapter.notifyDataSetChanged()
            summaryView.text = getString(
                R.string.merge_summary,
                sources.sumOf { it.chapters },
                sources.size,
                sources.sumOf { it.sizeBytes } / (1024 * 1024)
            )
            showWarnings(result.optJSONArray("warnings"))
            applySuggestedTocStyle(result.optString("suggested_toc_style", ""))
            applySuggestedLabels(result.optBoolean("suggested_shorten_labels", false))
        }
    }

    /**
     * Show the file the merge will write, so its name is never a surprise.
     *
     * Mirrors epub_merge.default_output_path: the title becomes the file name,
     * with the characters a file name cannot hold removed; with no title the base
     * book's name is used with a " (merged)" suffix.
     */
    private fun showOutputName(title: String) {
        val stem = title.replace(Regex("[\\\\/:*?\"<>|]"), "").trim().trim('.').take(120)
        val name = if (stem.isNotBlank()) {
            "$stem.epub"
        } else {
            val base = sources.firstOrNull()?.path?.substringAfterLast('/')
                ?.removeSuffix(".epub") ?: "merged"
            "$base (merged).epub"
        }
        outputNameView.text = getString(R.string.merge_output_name, name)
    }

    /** Tick the TOC style Python thinks fits, unless the user already chose one. */
    private fun applySuggestedTocStyle(suggested: String) {
        if (tocStyleChosen || suggested.isBlank()) return
        val id = if (suggested == "flat") R.id.mergeTocFlat else R.id.mergeTocSections
        tocStyleGroup.check(id)
    }

    /** Tick the chapter-name options Python thinks fit, unless the user chose. */
    private fun applySuggestedLabels(shorten: Boolean) {
        if (labelsChosen || !shorten) return
        shortenLabelsBox.isChecked = true
    }

    /** 'flat' or 'sections', from whichever radio button is ticked. */
    private fun selectedTocStyle(): String =
        if (tocStyleGroup.checkedRadioButtonId == R.id.mergeTocFlat) "flat" else "sections"

    private fun showWarnings(items: JSONArray?) {
        val lines = mutableListOf<String>()
        if (items != null) {
            for (index in 0 until items.length()) {
                lines.add("• " + items.optString(index))
            }
        }
        if (sources.firstOrNull()?.tocEntries == 0) {
            lines.add("• " + getString(R.string.merge_warn_first_no_toc))
        }
        if (lines.isEmpty()) {
            warningsView.visibility = View.GONE
        } else {
            warningsView.text = lines.joinToString("\n")
            warningsView.visibility = View.VISIBLE
        }
    }

    private fun startMerge() {
        if (sources.size < 2) {
            toast(getString(R.string.merge_need_two))
            return
        }
        val request = OneTimeWorkRequestBuilder<MergeBooksWorker>()
            .setInputData(
                workDataOf(
                    MergeBooksWorker.KEY_PATHS to sources.map { it.path }.toTypedArray(),
                    MergeBooksWorker.KEY_TITLE to titleField.text.toString().trim(),
                    MergeBooksWorker.KEY_AUTHOR to authorField.text.toString().trim(),
                    MergeBooksWorker.KEY_BASE_INDEX to 0,
                    MergeBooksWorker.KEY_COVER to sources.first().cover,
                    MergeBooksWorker.KEY_TOC_STYLE to selectedTocStyle(),
                    MergeBooksWorker.KEY_SHORTEN_LABELS to shortenLabelsBox.isChecked,
                    MergeBooksWorker.KEY_RENUMBER_CHAPTERS to renumberChaptersBox.isChecked,
                )
            )
            .build()
        workId = request.id
        WorkManager.getInstance(this).enqueue(request)
        observeWork()
    }

    private fun observeWork() {
        val id = workId ?: return
        progressBar.visibility = View.VISIBLE
        mergeButton.isEnabled = false
        summaryView.text = getString(R.string.merge_running)
        WorkManager.getInstance(this).getWorkInfoByIdLiveData(id).observe(this) { info ->
            when (info?.state) {
                WorkInfo.State.SUCCEEDED -> {
                    // Only the path travels back: the worker has already upserted
                    // the book, and MainActivity re-reads the store from it.
                    val mergedPath =
                        info.outputData.getString(MergeBooksWorker.KEY_OUTPUT).orEmpty()
                    setResult(
                        RESULT_OK,
                        android.content.Intent().putExtra("merged_path", mergedPath)
                    )
                    toast(
                        info.outputData.getString(MergeBooksWorker.KEY_MESSAGE)
                            ?: getString(R.string.merge_done)
                    )
                    finish()
                }
                WorkInfo.State.FAILED -> {
                    progressBar.visibility = View.GONE
                    mergeButton.isEnabled = true
                    val error = info.outputData.getString(MergeBooksWorker.KEY_ERROR)
                        ?: getString(R.string.merge_failed)
                    summaryView.text = getString(R.string.merge_failed_with, error)
                    toast(error)
                }
                else -> Unit
            }
        }
    }

    private fun move(position: Int, delta: Int) {
        val target = position + delta
        if (target < 0 || target >= sources.size) return
        val moved = sources.removeAt(position)
        sources.add(target, moved)
        adapter.notifyItemMoved(position, target)
        adapter.notifyItemRangeChanged(0, sources.size)
        if (position == 0 || target == 0) {
            // The base changed, so the defaults should follow it.
            titleField.setText(sources.first().title)
            authorField.setText(sources.first().author)
        }
    }

    private fun toast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }

    private inner class SourceAdapter : RecyclerView.Adapter<SourceAdapter.Holder>() {

        inner class Holder(view: View) : RecyclerView.ViewHolder(view) {
            val index: TextView = view.findViewById(R.id.mergeRowIndex)
            val title: TextView = view.findViewById(R.id.mergeRowTitle)
            val meta: TextView = view.findViewById(R.id.mergeRowMeta)
            val up: ImageButton = view.findViewById(R.id.mergeRowUp)
            val down: ImageButton = view.findViewById(R.id.mergeRowDown)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder =
            Holder(
                LayoutInflater.from(parent.context)
                    .inflate(R.layout.item_merge_source, parent, false)
            )

        override fun getItemCount(): Int = sources.size

        override fun onBindViewHolder(holder: Holder, position: Int) {
            val source = sources[position]
            // Just the number: "1 · base" was too wide for this column and wrapped.
            holder.index.text = getString(R.string.merge_index_plain, position + 1)
            holder.title.text = source.title
            holder.meta.text = getString(
                if (position == 0) R.string.merge_row_meta_base else R.string.merge_row_meta,
                source.chapters, source.tocEntries
            )
            val canMoveUp = position > 0
            val canMoveDown = position < sources.size - 1
            holder.up.isEnabled = canMoveUp
            holder.up.alpha = if (canMoveUp) 1f else 0.3f
            holder.down.isEnabled = canMoveDown
            holder.down.alpha = if (canMoveDown) 1f else 0.3f
            holder.up.setOnClickListener { move(position, -1) }
            holder.down.setOnClickListener { move(position, 1) }
        }
    }
}