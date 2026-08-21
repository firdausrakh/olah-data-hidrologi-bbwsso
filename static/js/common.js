(function () {
    'use strict';

    const authBootstrap = window.__HYDRO_AUTH_BOOTSTRAP__ || {};
    const HydroUI = {
        authState: {
            authenticated: !!authBootstrap.authenticated,
            configured: authBootstrap.configured !== false,
            loaded: true,
        },
        pad2(value) {
            return String(value).padStart(2, '0');
        },
        isoDate(date) {
            return `${date.getFullYear()}-${this.pad2(date.getMonth() + 1)}-${this.pad2(date.getDate())}`;
        },
        escapeHtml(value) {
            return String(value ?? '').replace(/[&<>"']/g, char => ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
            }[char]));
        },
        datepickerBase(extra = {}) {
            return {
                language: 'id',
                autoclose: true,
                todayHighlight: true,
                enableOnReadonly: true,
                orientation: 'bottom auto',
                ...extra,
            };
        },
        isDark() {
            return document.documentElement.getAttribute('data-theme') === 'dark';
        },
        applyTheme(theme) {
            const dark = theme === 'dark';
            if (dark) document.documentElement.setAttribute('data-theme', 'dark');
            else document.documentElement.removeAttribute('data-theme');
            localStorage.setItem('theme', dark ? 'dark' : 'light');
            const icon = document.getElementById('themeIcon');
            if (icon) icon.setAttribute('data-lucide', dark ? 'sun' : 'moon');
            if (window.lucide) window.lucide.createIcons();
            document.dispatchEvent(new CustomEvent('hydro:themechange', {detail: {theme: dark ? 'dark' : 'light'}}));
        },
        toggleTheme() {
            this.applyTheme(this.isDark() ? 'light' : 'dark');
        },
        refreshIcons() {
            if (window.lucide) window.lucide.createIcons();
        },
        enhanceFieldHelp(root = document) {
            let tooltip = document.getElementById('fieldHelpTooltip');
            if (!tooltip) {
                tooltip = document.createElement('div');
                tooltip.id = 'fieldHelpTooltip';
                tooltip.className = 'field-help-tooltip';
                tooltip.setAttribute('role', 'tooltip');
                document.body.appendChild(tooltip);
            }
            const hideTip = () => {
                tooltip.classList.remove('visible');
                tooltip.setAttribute('aria-hidden', 'true');
            };
            const showTip = helper => {
                const tip = String(helper.dataset.tip || '').trim();
                if (!tip) return;
                tooltip.textContent = tip;
                tooltip.setAttribute('aria-hidden', 'false');
                tooltip.classList.add('visible');
                tooltip.style.visibility = 'hidden';
                tooltip.style.left = '0px';
                tooltip.style.top = '0px';
                const rect = helper.getBoundingClientRect();
                const tipRect = tooltip.getBoundingClientRect();
                const margin = 10;
                const viewportWidth = document.documentElement.clientWidth;
                const viewportHeight = document.documentElement.clientHeight;
                const left = Math.max(margin, Math.min(rect.right - tipRect.width, viewportWidth - tipRect.width - margin));
                let top = rect.bottom + 7;
                if (top + tipRect.height > viewportHeight - margin) top = Math.max(margin, rect.top - tipRect.height - 7);
                tooltip.style.left = `${Math.round(left)}px`;
                tooltip.style.top = `${Math.round(top)}px`;
                tooltip.style.visibility = '';
            };
            root.querySelectorAll('label[data-help]').forEach(label => {
                if (label.querySelector('.field-help')) return;
                const tip = String(label.dataset.help || '').trim();
                if (!tip) return;
                const helper = document.createElement('span');
                helper.className = 'field-help';
                helper.tabIndex = 0;
                helper.setAttribute('role', 'button');
                helper.setAttribute('aria-label', `Informasi: ${tip}`);
                helper.setAttribute('aria-describedby', 'fieldHelpTooltip');
                helper.dataset.tip = tip;
                helper.innerHTML = '<i data-lucide="info"></i>';
                helper.addEventListener('mouseenter', () => showTip(helper));
                helper.addEventListener('mouseleave', hideTip);
                helper.addEventListener('focus', () => showTip(helper));
                helper.addEventListener('blur', hideTip);
                label.appendChild(helper);
            });
            window.addEventListener('scroll', hideTip, true);
            window.addEventListener('resize', hideTip);
            this.refreshIcons();
        },
        applyAuthState(authenticated, configured = true) {
            this.authState = {authenticated: !!authenticated, configured: !!configured, loaded: true};
            document.body?.classList.toggle('telemetry-authenticated', !!authenticated);
            document.body?.classList.toggle('telemetry-manual-only', !authenticated);

            const status = document.getElementById('connectionStatus');
            const icon = document.getElementById('connectionIcon');
            const text = document.getElementById('connectionText');
            if (status) {
                status.classList.toggle('connected', !!authenticated);
                status.classList.toggle('disconnected', !authenticated);
                status.title = authenticated ? 'Terhubung ke server telemetri' : 'Belum login — mode manual';
                status.setAttribute('aria-label', status.title);
            }
            if (icon) icon.setAttribute('data-lucide', authenticated ? 'wifi' : 'wifi-off');
            if (text) text.textContent = authenticated ? 'Terhubung' : 'Manual';

            const monitorLink = document.getElementById('monitorNavLink');
            if (monitorLink) {
                monitorLink.classList.toggle('disabled', !authenticated);
                monitorLink.setAttribute('aria-disabled', authenticated ? 'false' : 'true');
                monitorLink.tabIndex = authenticated ? 0 : -1;
            }

            this.refreshIcons();
            document.dispatchEvent(new CustomEvent('hydro:authchange', {detail: this.authState}));
        },
        async refreshAuthState() {
            try {
                const res = await fetch('/api/auth/status', {cache: 'no-store'});
                const data = await res.json();
                this.applyAuthState(!!data.authenticated, data.configured !== false);
                return this.authState;
            } catch (_err) {
                // Pertahankan state yang sudah dibootstrap oleh Flask. Gangguan
                // sesaat pada endpoint status tidak boleh membuat header berkedip
                // dari "Terhubung" menjadi "Manual".
                return this.authState;
            }
        },
        requestAuth() {
            if (typeof window.openTelemetryAuth === 'function') {
                window.openTelemetryAuth();
                return;
            }
            window.location.href = '/?auth=1';
        },
    };

    window.HydroUI = HydroUI;

    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') document.documentElement.setAttribute('data-theme', 'dark');

    document.addEventListener('DOMContentLoaded', () => {
        const icon = document.getElementById('themeIcon');
        if (icon) icon.setAttribute('data-lucide', HydroUI.isDark() ? 'sun' : 'moon');
        const button = document.getElementById('themeToggleBtn');
        if (button) button.addEventListener('click', () => HydroUI.toggleTheme());

        const connection = document.getElementById('connectionStatus');
        if (connection) connection.addEventListener('click', () => {
            if (!HydroUI.authState.authenticated) HydroUI.requestAuth();
        });

        const monitorLink = document.getElementById('monitorNavLink');
        if (monitorLink) monitorLink.addEventListener('click', event => {
            if (!HydroUI.authState.authenticated) {
                event.preventDefault();
                HydroUI.requestAuth();
            }
        });

        HydroUI.enhanceFieldHelp();
        HydroUI.refreshAuthState();
    });
})();
