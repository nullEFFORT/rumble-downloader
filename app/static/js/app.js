// Video Downloader Frontend JS

// Auto-refresh stats every 30 seconds on dashboard
if (document.querySelector('.stats-grid')) {
    setInterval(async () => {
        try {
            const response = await fetch('/api/stats');
            const stats = await response.json();

            // Update stat cards if they exist
            const cards = document.querySelectorAll('.stat-card');
            cards.forEach(card => {
                const label = card.querySelector('.stat-label')?.textContent.toLowerCase();
                const value = card.querySelector('.stat-value');
                if (!label || !value) return;

                if (label.includes('pending')) value.textContent = stats.pending_videos;
                else if (label.includes('downloaded')) value.textContent = stats.completed_videos;
                else if (label.includes('failed')) value.textContent = stats.failed_videos;
                else if (label.includes('total channels')) value.textContent = stats.total_channels;
                else if (label.includes('active')) value.textContent = stats.enabled_channels;
                else if (label.includes('total videos')) value.textContent = stats.total_videos;
            });
        } catch (e) {
            console.error('Failed to refresh stats:', e);
        }
    }, 30000);
}

// Toast notification helper
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toast.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        padding: 1rem 1.5rem;
        background: ${type === 'error' ? '#f87171' : type === 'success' ? '#4ade80' : '#60a5fa'};
        color: ${type === 'error' || type === 'info' ? 'white' : 'black'};
        border-radius: 8px;
        z-index: 1000;
        animation: slideIn 0.3s ease;
    `;

    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Add CSS animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
`;
document.head.appendChild(style);
