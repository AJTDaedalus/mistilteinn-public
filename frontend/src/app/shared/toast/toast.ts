import { Component, signal, OnDestroy } from '@angular/core';

export interface ToastMessage {
  text: string;
  action?: { label: string; callback: () => void };
}

@Component({
  selector: 'app-toast',
  standalone: true,
  templateUrl: './toast.html',
  styleUrl: './toast.scss',
})
export class Toast implements OnDestroy {
  protected current = signal<ToastMessage | null>(null);
  private timer: ReturnType<typeof setTimeout> | null = null;

  show(text: string, action?: { label: string; callback: () => void }, durationMs = 8000) {
    if (this.timer) clearTimeout(this.timer);
    this.current.set({ text, action });
    this.timer = setTimeout(() => this.dismiss(), durationMs);
  }

  dismiss() {
    if (this.timer) { clearTimeout(this.timer); this.timer = null; }
    this.current.set(null);
  }

  ngOnDestroy() {
    if (this.timer) clearTimeout(this.timer);
  }
}
