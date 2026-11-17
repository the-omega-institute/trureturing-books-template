<!--
  Cover and closing slides: the default frame without header and footer, plus the cover furniture —
  the book code, the followed trureturing branch (legacy: pinned commit), a horizon grid, a HUD dial with a golden spiral and
  a meta strip from the headmatter. Put a kicker, an h1.display and a lead paragraph in the body.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useSlideContext } from '@slidev/client'
import { pinned } from '../lean'
import { t } from '../i18n'
import PageNo from '../components/PageNo.vue'

defineOptions({ inheritAttrs: false })
const props = defineProps<{ class?: string }>()
const { $slidev } = useSlideContext()
const deck = computed<Record<string, string>>(() => ($slidev.configs as any).deck ?? {})

// HUD dial: tick ring, and a golden spiral r = a·φ^(2θ/π) (a quarter turn grows by φ).
const PHI = (1 + Math.sqrt(5)) / 2
const polar = (r: number, deg: number) => [r * Math.cos((deg * Math.PI) / 180), r * Math.sin((deg * Math.PI) / 180)]
const ticks = Array.from({ length: 72 }, (_, i) => {
  const major = i % 6 === 0
  const [x1, y1] = polar(major ? 250 : 262, i * 5)
  const [x2, y2] = polar(278, i * 5)
  return { x1, y1, x2, y2, major }
})
const spiral = (() => {
  const pts: string[] = []
  for (let th = -5.5 * Math.PI; th <= 1.5 * Math.PI; th += Math.PI / 48) {
    const r = 118 * PHI ** ((2 * th) / Math.PI) / PHI ** 2
    pts.push(`${(r * Math.cos(th)).toFixed(1)},${(r * Math.sin(th)).toFixed(1)}`)
  }
  return pts.join(' ')
})()
const arc = (r: number, from: number, to: number) => {
  const [x1, y1] = polar(r, from)
  const [x2, y2] = polar(r, to)
  return `M${x1.toFixed(1)},${y1.toFixed(1)} A${r},${r} 0 ${to - from > 180 ? 1 : 0} 1 ${x2.toFixed(1)},${y2.toFixed(1)}`
}
</script>

<template>
  <div class="slide cover" :class="props.class">
    <div class="tr-fx" aria-hidden="true"><i class="bracket tl" /><i class="bracket tr" /><i class="bracket bl" /><i class="bracket br" /></div>
    <div class="cover-grid" aria-hidden="true" />
    <svg class="cover-hud" viewBox="-310 -310 620 620" aria-hidden="true">
      <circle class="hud-ring" r="296" />
      <line v-for="(tk, i) in ticks" :key="i" :class="tk.major ? 'hud-tick major' : 'hud-tick'" :x1="tk.x1" :y1="tk.y1" :x2="tk.x2" :y2="tk.y2" />
      <path class="hud-arc" :d="arc(296, -150, -60)" />
      <path class="hud-arc alt" :d="arc(296, 30, 75)" />
      <circle class="hud-ring dashed" r="196" />
      <line class="hud-cross" x1="-310" y1="0" x2="310" y2="0" />
      <line class="hud-cross" x1="0" y1="-310" x2="0" y2="310" />
      <polyline class="hud-spiral glow" :points="spiral" />
      <polyline class="hud-spiral" :points="spiral" />
      <circle class="hud-dot" r="6" />
    </svg>
    <div class="cover-top">
      <span class="cover-code">{{ deck.code }}</span>
      <span v-if="pinned.short" class="cover-pin">LEAN 4<span class="cover-pin-sep">/</span>trureturing<span class="ftr-at">@</span>{{ pinned.short }}</span>
    </div>
    <div class="body cover-body"><slot /></div>
    <div class="cover-meta">
      <div v-if="deck.book"><span class="k">{{ t('slides.book') }}</span><span class="v">{{ deck.book }}</span></div>
      <div v-if="deck.version"><span class="k">{{ t('slides.version') }}</span><span class="v">v{{ deck.version }}</span></div>
      <div v-if="pinned.short"><span class="k">{{ t('slides.commit') }}</span><span class="v mono">{{ pinned.short }}</span></div>
      <PageNo />
    </div>
  </div>
</template>
