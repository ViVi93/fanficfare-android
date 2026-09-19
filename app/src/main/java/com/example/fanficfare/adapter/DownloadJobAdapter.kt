package com.example.fanficfare.adapter

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.example.fanficfare.R
import com.example.fanficfare.data.local.DownloadJobEntity

class DownloadJobAdapter(
    private val onRetry: (DownloadJobEntity) -> Unit,
    private val onRemove: (DownloadJobEntity) -> Unit
) : ListAdapter<DownloadJobEntity, DownloadJobAdapter.JobViewHolder>(DiffCallback) {

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): JobViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_download_job, parent, false)
        return JobViewHolder(view)
    }

    override fun onBindViewHolder(holder: JobViewHolder, position: Int) {
        holder.bind(getItem(position), onRetry, onRemove)
    }

    class JobViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val textTitle: TextView = itemView.findViewById(R.id.textTitle)
        private val textMeta: TextView = itemView.findViewById(R.id.textMeta)
        private val textStatus: TextView = itemView.findViewById(R.id.textStatus)
        private val badgeBg: View = itemView.findViewById(R.id.statusBadgeBackground)
        private val textError: TextView = itemView.findViewById(R.id.textError)
        private val iconStatus: ImageView = itemView.findViewById(R.id.iconStatus)
        private val buttonRetry: Button = itemView.findViewById(R.id.buttonRetry)
        private val buttonRemove: Button = itemView.findViewById(R.id.buttonRemove)

        fun bind(
            job: DownloadJobEntity,
            onRetry: (DownloadJobEntity) -> Unit,
            onRemove: (DownloadJobEntity) -> Unit
        ) {
            val context = itemView.context

            // Title
            textTitle.text = when {
                job.inputUrl?.isNotBlank() == true -> {
                    val host = android.net.Uri.parse(job.inputUrl)?.host
                    host ?: job.inputUrl
                }
                job.inputPath?.isNotBlank() == true -> {
                    java.io.File(job.inputPath).nameWithoutExtension
                }
                else -> context.getString(R.string.job_unknown_title)
            }

            // Meta line
            val typeLabel = when (job.type) {
                "download" -> context.getString(R.string.job_type_download)
                "update" -> context.getString(R.string.job_type_update)
                "force_download" -> context.getString(R.string.job_type_force_download)
                "metadata" -> context.getString(R.string.job_type_metadata)
                else -> job.type
            }
            val createdStr = android.text.format.DateFormat.format(
                "MMM d, HH:mm", job.createdAt
            ).toString()
            textMeta.text = "$typeLabel · $createdStr"

            // Status badge
            val (statusText, statusColorRes, iconVisible) = when (job.status) {
                "queued" -> Triple(
                    context.getString(R.string.status_queued),
                    R.color.fanficfare_tertiary,
                    true
                )
                "running" -> Triple(
                    context.getString(R.string.status_running),
                    R.color.fanficfare_secondary,
                    true
                )
                "failed" -> Triple(
                    context.getString(R.string.status_failed),
                    R.color.fanficfare_error,
                    false
                )
                "cancelled" -> Triple(
                    context.getString(R.string.status_cancelled),
                    R.color.fanficfare_on_surface_variant,
                    false
                )
                "success" -> Triple(
                    context.getString(R.string.status_complete),
                    R.color.fanficfare_secondary,
                    false
                )
                else -> Triple(
                    job.status.replaceFirstChar { it.uppercase() },
                    R.color.fanficfare_on_surface_variant,
                    false
                )
            }
            textStatus.text = statusText
            val baseColor = context.getColor(statusColorRes)
            textStatus.setTextColor(baseColor)

            val badgeBgDrawable = android.graphics.drawable.GradientDrawable()
            badgeBgDrawable.shape = android.graphics.drawable.GradientDrawable.RECTANGLE
            badgeBgDrawable.setCornerRadius(16f * context.resources.displayMetrics.density)
            badgeBgDrawable.setColor(
                android.graphics.Color.argb(
                    40,
                    android.graphics.Color.red(baseColor),
                    android.graphics.Color.green(baseColor),
                    android.graphics.Color.blue(baseColor)
                )
            )
            badgeBg.background = badgeBgDrawable

            iconStatus.visibility = if (iconVisible) View.VISIBLE else View.GONE

            // Error
            if (job.status == "failed" && !job.error.isNullOrBlank()) {
                textError.visibility = View.VISIBLE
                textError.text = job.error
            } else {
                textError.visibility = View.GONE
            }

            // Retry button — show for failed, queued, cancelled
            val showRetry = job.status == "failed" ||
                job.status == "queued" || job.status == "cancelled"
            buttonRetry.visibility = if (showRetry) View.VISIBLE else View.GONE
            buttonRetry.setOnClickListener { onRetry(job) }

            // Remove button — always available
            buttonRemove.setOnClickListener { onRemove(job) }
        }
    }

    companion object {
        private val DiffCallback = object : DiffUtil.ItemCallback<DownloadJobEntity>() {
            override fun areItemsTheSame(old: DownloadJobEntity, new: DownloadJobEntity): Boolean =
                old.id == new.id

            override fun areContentsTheSame(old: DownloadJobEntity, new: DownloadJobEntity): Boolean =
                old == new
        }
    }
}
