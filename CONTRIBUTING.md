# Contributing — hermes-infisical-source

Gracias por colaborar. El proyecto es pequeño: la metodología es **main protegido + ramas cortas + PR con CI y revisión**. Sin GitFlow, sin develop, sin ramas de release.

## Flujo de colaboración

```
main (protegida)
   └─ git checkout -b feature/<descripcion-corta>
   └─ (trabajas + commiteas)
   └─ git push origin feature/<descripcion-corta>
   └─ GitHub → New Pull Request → base: main ← compare: feature/...
         └─ CI (conformance 10/10) debe pasar
         └─ 1 revisión aprobada → merge (squash)
```

## Pasos concretos

```bash
# 1. Clona y prepara
git clone git@github.com:maurorosero/hermes-infisical-source.git
cd hermes-infisical-source

# 2. Rama desde main SIEMPRE al día
git checkout main && git pull
git checkout -b feature/mi-cambio

# 3. Trabaja, commitea y sube
git add ...
git commit -m "tipo: descripción breve"
git push -u origin feature/mi-cambio

# 4. Abre el PR a main (no a otra rama)
#    - CI debe quedar VERDE antes de pedir revisión
#    - Describe qué cambia y por qué (y cómo se probó)
```

## Reglas

1. **Nunca se pushea directo a `main`** — solo PRs.
2. **CI debe pasar** — conformance kit (10 tests) corre en cada PR. Rojo = no se mergea.
3. **Revisión recomendada (no bloqueante)** — repos personal de mantenedor único: el autor no se auto-aprueba y GitHub no permite review del propio PR; la revisión es buena práctica cuando haya 2+ colaboradores. Con 1 mantenedor, el merge exige solo CI verde.
4. **Ramas cortas** (`feature/...`) — se borran tras el merge.
5. **Commit firma GPG/SSH** — se prefiere firma (el repo usa commits firmados).
6. **Conventional Commits** — `feat:`, `fix:`, `docs:`, `ci:`, `refactor:` + descripción corta.

## Probar localmente (sin Infisical)

El plugin no requiere Infisical para probarse — la conformance corre con config vacía
(`{}`, `{"enabled": true}`) y verifica el contrato, no la conexión:

```bash
pip install pytest pyyaml
git clone --depth 1 https://github.com/NousResearch/hermes-agent /tmp/hermes-src
PYTHONPATH=/tmp/hermes-src pytest tests/ -v     # esperado: 10 passed
```

> Si vas a probar la integración real necesitas un proyecto Infisical + CLI — ver `docs/INTEGRACION.md`.

## Reportar bugs / ideas

Abre un **Issue** en GitHub con: qué esperabas, qué pasó, pasos para reproducir,
y si aplica, el stack trace. Sin plantilla obligatoria — clara y breve basta.

## Contacto

- Mantenedor: Mauro Rosero Pérez (`maurorosero`)
- Autor original: Alan Rosero One (OPENTECH / ROSERO ONE)
