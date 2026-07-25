import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
} from 'react'
import { useNavigate } from 'react-router-dom'

/*
 * Transisi antar-halaman ala situs award: lingkaran gradien mengembang dari
 * TITIK KLIK menutup layar, logo muncul sekejap, lalu halaman tujuan terbuka.
 * Dipasang sekali di App; halaman mana pun tinggal panggil usePageTransition().
 */

type Fase = 'diam' | 'tutup' | 'buka'

const TUTUP_MS = 620 // lingkaran mengembang menutup layar
const TAHAN_MS = 300 // logo tampil sejenak (halaman ditukar di baliknya)
const BUKA_MS = 520 // tirai memudar membuka halaman baru

const TransitionCtx = createContext<(to: string, e?: React.MouseEvent) => void>(
  () => {},
)

/** Navigasi dengan tirai transisi. Pakai di onClick Link: (e) => pindah('/login', e). */
export function usePageTransition() {
  return useContext(TransitionCtx)
}

export function TransitionProvider({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  const [fase, setFase] = useState<Fase>('diam')
  const [pusat, setPusat] = useState({ x: 0, y: 0, r: 1000 })
  const sibuk = useRef(false)

  const pindah = useCallback(
    (to: string, e?: React.MouseEvent) => {
      if (e) {
        // Hormati buka-tab-baru (ctrl/cmd/shift/klik-tengah): biarkan browser.
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0)
          return
        e.preventDefault()
      }
      if (sibuk.current) return
      sibuk.current = true
      const x = e?.clientX ?? window.innerWidth / 2
      const y = e?.clientY ?? window.innerHeight * 0.4
      // Radius = jarak titik klik ke sudut layar terjauh -> pasti menutup penuh.
      const r = Math.hypot(
        Math.max(x, window.innerWidth - x),
        Math.max(y, window.innerHeight - y),
      )
      setPusat({ x, y, r })
      setFase('tutup')
      window.setTimeout(() => {
        navigate(to)
        window.scrollTo(0, 0)
        window.setTimeout(() => {
          setFase('buka')
          window.setTimeout(() => {
            setFase('diam')
            sibuk.current = false
          }, BUKA_MS)
        }, TAHAN_MS)
      }, TUTUP_MS)
    },
    [navigate],
  )

  return (
    <TransitionCtx.Provider value={pindah}>
      {children}
      {fase !== 'diam' && (
        <div
          className={`transisi-root ${fase === 'buka' ? 'transisi-buka' : ''}`}
          aria-hidden="true"
        >
          <div
            className="transisi-lingkaran"
            style={{
              left: pusat.x,
              top: pusat.y,
              width: pusat.r * 2,
              height: pusat.r * 2,
            }}
          />
          <div className="transisi-logo">
            <span className="relative grid h-24 w-24 place-items-center">
              <span
                className="ring-spin absolute -inset-2 rounded-full opacity-80 blur-md"
                style={{
                  background:
                    'conic-gradient(from 0deg, #3385fc, #10b981, #06b6d4, #3385fc)',
                }}
              />
              <img
                src="/logos/unismuh-seal.png"
                alt=""
                className="relative h-24 w-24 object-contain drop-shadow-2xl"
              />
            </span>
            <p className="mt-4 text-sm font-bold tracking-[0.25em] text-white/80">
              UNISMUH COMPUTEHUB
            </p>
          </div>
        </div>
      )}
    </TransitionCtx.Provider>
  )
}
