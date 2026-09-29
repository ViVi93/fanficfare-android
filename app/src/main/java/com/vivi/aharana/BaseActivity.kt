package com.vivi.aharana

import android.os.Bundle
import android.view.View
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updatePadding
import com.google.android.material.color.ColorContrast
import com.google.android.material.color.ColorContrastOptions
import com.google.android.material.color.DynamicColors
import com.google.android.material.color.DynamicColorsOptions
import com.google.android.material.snackbar.Snackbar

/**
 * Shared base for every screen.
 *
 * Two responsibilities:
 *
 * 1. **Edge-to-edge.** Android 15 (API 35) enforces edge-to-edge for apps that target SDK 35 and
 *    ignores `WindowCompat.setDecorFitsSystemWindows(window, true)`, so the old per-activity opt-out
 *    is both deprecated and ineffective. We call [enableEdgeToEdge] once here and let each screen
 *    inset the views that need it via the helpers below.
 *
 * 2. **Colour mode.** Picks the AMOLED theme and applies the Material You or system-contrast
 *    overlay. Both live here rather than in `Application` on purpose: Material Components applies
 *    dynamic colour *before* activities are created, so an Application-level contrast overlay would
 *    be silently overwritten. One place, one authority over the activity theme.
 *
 * The inset helpers add the system insets *on top of* the padding declared in XML (the base padding
 * is captured once, so repeated inset callbacks stay idempotent instead of accumulating).
 */
open class BaseActivity : AppCompatActivity() {

    protected val appPrefs by lazy { getSharedPreferences(PREFS, MODE_PRIVATE) }

    override fun onCreate(savedInstanceState: Bundle?) {
        applyBaseTheme()
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        // Runs before the subclass inflates its layout, because views capture the resolved
        // theme colours at inflation time.
        applyColourMode()
    }

    /**
     * Override to opt out of the AMOLED theme — used by the translucent share receiver, which
     * must keep its own translucent theme rather than becoming opaque.
     */
    protected open fun supportsAmoledTheme(): Boolean = true

    private fun applyBaseTheme() {
        if (!supportsAmoledTheme()) return
        if (appPrefs.getString(KEY_THEME_MODE, THEME_SYSTEM) == THEME_AMOLED) {
            setTheme(R.style.Theme_Aharana_Amoled)
        }
    }

    private fun applyColourMode() {
        val amoled = appPrefs.getString(KEY_THEME_MODE, THEME_SYSTEM) == THEME_AMOLED
        val materialYou = appPrefs.getBoolean(KEY_DYNAMIC_COLOR, true) &&
            DynamicColors.isDynamicColorAvailable()

        if (materialYou) {
            DynamicColors.applyToActivityIfAvailable(
                this,
                DynamicColorsOptions.Builder()
                    .setThemeOverlay(
                        if (amoled) R.style.ThemeOverlay_Aharana_DynamicColors_Amoled
                        else R.style.ThemeOverlay_Aharana_DynamicColors
                    )
                    .build()
            )
            return
        }

        // Material You off: honour the user's system contrast setting from our own overlays.
        // (With dynamic colour on, Android 14+ supplies contrast for free.)
        if (ColorContrast.isContrastAvailable()) {
            ColorContrast.applyToActivityIfAvailable(
                this,
                ColorContrastOptions.Builder()
                    .setMediumContrastThemeOverlay(R.style.ThemeOverlay_Aharana_Contrast_Medium)
                    .setHighContrastThemeOverlay(R.style.ThemeOverlay_Aharana_Contrast_High)
                    .build()
            )
        }
    }

    /**
     * In-place feedback, anchored to the activity content so it clears the system bars.
     *
     * Thread-safe on purpose: several callers already report completion from a background
     * thread, and Snackbar must be shown on the main thread. Posting instead of throwing keeps
     * those callers working unchanged.
     */
    protected fun showMessage(text: CharSequence) {
        val root = findViewById<View>(android.R.id.content) ?: return
        if (android.os.Looper.myLooper() == android.os.Looper.getMainLooper()) {
            Snackbar.make(root, text, Snackbar.LENGTH_LONG).show()
        } else {
            root.post { Snackbar.make(root, text, Snackbar.LENGTH_LONG).show() }
        }
    }

    /** String-resource overload, mirroring `Toast.makeText`'s resId form. */
    protected fun showMessage(@androidx.annotation.StringRes textRes: Int) =
        showMessage(getString(textRes))

    /** Pads [view]'s top by the status-bar inset. Use on app bars so their background extends
     *  behind the status bar while the content stays clear of it. */
    protected fun applyTopInset(view: View) =
        applyInsets(view, top = true, bottom = false, horizontal = false)

    /** Pads [view]'s bottom by the navigation-bar inset. Use on content that should keep its
     *  last row reachable above the gesture bar. Set [includeIme] on form screens so the keyboard
     *  cannot hide the focused field. */
    protected fun applyBottomInset(view: View, includeIme: Boolean = false) =
        applyInsets(view, top = false, bottom = true, horizontal = false, includeIme = includeIme)

    private fun applyInsets(
        view: View,
        top: Boolean,
        bottom: Boolean,
        horizontal: Boolean,
        includeIme: Boolean = false
    ) {
        // Captured once: the padding declared in XML is the baseline the insets are added to.
        val baseLeft = view.paddingLeft
        val baseTop = view.paddingTop
        val baseRight = view.paddingRight
        val baseBottom = view.paddingBottom

        ViewCompat.setOnApplyWindowInsetsListener(view) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val imeBottom = if (includeIme) {
                insets.getInsets(WindowInsetsCompat.Type.ime()).bottom
            } else {
                0
            }
            v.updatePadding(
                left = baseLeft + if (horizontal) bars.left else 0,
                top = baseTop + if (top) bars.top else 0,
                right = baseRight + if (horizontal) bars.right else 0,
                bottom = baseBottom + if (bottom) maxOf(bars.bottom, imeBottom) else 0
            )
            insets
        }
        ViewCompat.requestApplyInsets(view)
    }

    companion object {
        /** Shared preferences file, also read by Settings and Main. */
        const val PREFS = "fanficfare_prefs"
        const val KEY_THEME_MODE = "ui_theme_mode"
        const val KEY_DYNAMIC_COLOR = "dynamic_color_enabled"

        /** `ui_theme_mode` values. */
        const val THEME_SYSTEM = "system"
        const val THEME_LIGHT = "light"
        const val THEME_DARK = "dark"
        const val THEME_AMOLED = "amoled"
    }
}