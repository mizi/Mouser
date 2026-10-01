import QtQuick

// Draws the stroke one wheel click produces: speed per frame, and the distance
// it adds up to. Canvas is QtQuick core, so this needs no extra Qt module in
// the PyInstaller spec; QtCharts and QtQuick.Shapes both would.
Item {
    id: graph

    // [{ frame, speed, total, boosted }], straight from the backend so the
    // drawing and the injector read the same curve.
    property var samples: []
    property int brakePoint: 4
    property var theme
    property string framesLabel: "Frames"
    property string speedLabel: "Speed"
    property string distanceLabel: "Distance"
    property string boostedLabel: "At full acceleration"
    property string brakeLabel: "Brake"
    property string fontFamily: "sans-serif"

    implicitHeight: 180

    readonly property real peakSpeed: {
        var peak = 0
        for (var i = 0; i < samples.length; i++)
            peak = Math.max(peak, samples[i].boosted || samples[i].speed || 0)
        return peak
    }
    // Derived rather than fixed: at speed 50 the peak is 25 px per frame, and a
    // hardcoded 0-5 axis would draw the curve off the top of the box.
    readonly property real speedAxisMax: Math.max(5, Math.ceil(peakSpeed / 5) * 5)
    readonly property real distanceAxisMax: {
        var total = samples.length ? samples[samples.length - 1].total : 0
        return Math.max(10, Math.ceil(total / 10) * 10)
    }
    readonly property int frameAxisMax: Math.max(1, samples.length - 1)

    onSamplesChanged: plot.requestPaint()
    onBrakePointChanged: plot.requestPaint()
    onThemeChanged: plot.requestPaint()
    onWidthChanged: plot.requestPaint()
    onHeightChanged: plot.requestPaint()

    // No MouseArea at all, so a wheel event over the graph scrolls the page
    // rather than being swallowed by a decoration.
    Canvas {
        id: plot
        anchors.fill: parent
        renderStrategy: Canvas.Cooperative

        readonly property int padLeft: 44
        readonly property int padRight: 44
        readonly property int padTop: 14
        readonly property int padBottom: 26

        function plotX(frame) {
            var usable = width - padLeft - padRight
            return padLeft + (frame / graph.frameAxisMax) * usable
        }

        function plotY(value, axisMax) {
            var usable = height - padTop - padBottom
            return padTop + usable - (value / axisMax) * usable
        }

        function polyline(ctx, key, axisMax, color, dashed, fill) {
            if (!graph.samples.length)
                return
            ctx.save()
            ctx.strokeStyle = color
            ctx.lineWidth = 2
            ctx.setLineDash(dashed ? [5, 4] : [])
            ctx.beginPath()
            for (var i = 0; i < graph.samples.length; i++) {
                var x = plotX(graph.samples[i].frame)
                var y = plotY(graph.samples[i][key] || 0, axisMax)
                if (i === 0)
                    ctx.moveTo(x, y)
                else
                    ctx.lineTo(x, y)
            }
            ctx.stroke()
            if (fill) {
                ctx.lineTo(plotX(graph.samples[graph.samples.length - 1].frame),
                           plotY(0, axisMax))
                ctx.lineTo(plotX(0), plotY(0, axisMax))
                ctx.closePath()
                ctx.globalAlpha = 0.15
                ctx.fillStyle = color
                ctx.fill()
            }
            ctx.restore()
        }

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            if (!graph.theme || !graph.samples.length)
                return

            var left = padLeft
            var right = width - padRight
            var top = padTop
            var bottom = height - padBottom

            // Gridlines
            ctx.save()
            ctx.strokeStyle = graph.theme.border
            ctx.lineWidth = 1
            ctx.globalAlpha = 0.6
            for (var row = 0; row <= 4; row++) {
                var y = top + (bottom - top) * row / 4
                ctx.beginPath()
                ctx.moveTo(left, y)
                ctx.lineTo(right, y)
                ctx.stroke()
            }
            ctx.restore()

            // Brake point
            if (graph.brakePoint > 0 && graph.brakePoint <= graph.frameAxisMax) {
                ctx.save()
                ctx.strokeStyle = graph.theme.textDim
                ctx.lineWidth = 1
                ctx.setLineDash([3, 3])
                var bx = plotX(graph.brakePoint)
                ctx.beginPath()
                ctx.moveTo(bx, top)
                ctx.lineTo(bx, bottom)
                ctx.stroke()
                ctx.restore()
            }

            // The acceleration ceiling. Live gain depends on how fast the wheel
            // is actually turning, so at rest it is 1.0; this ghost is what the
            // slider can reach, not what is happening right now.
            polyline(ctx, "boosted", graph.speedAxisMax, graph.theme.textDim,
                     false, false)
            polyline(ctx, "total", graph.distanceAxisMax, graph.theme.warning,
                     true, false)
            polyline(ctx, "speed", graph.speedAxisMax, graph.theme.accent,
                     false, true)

            // Axis labels
            ctx.save()
            ctx.fillStyle = graph.theme.textDim
            ctx.font = "10px " + graph.fontFamily
            ctx.textBaseline = "middle"
            ctx.textAlign = "right"
            for (var tick = 0; tick <= 4; tick++) {
                var ly = top + (bottom - top) * (4 - tick) / 4
                ctx.fillText(Math.round(graph.speedAxisMax * tick / 4),
                             left - 6, ly)
            }
            ctx.textAlign = "left"
            for (var rtick = 0; rtick <= 4; rtick++) {
                var ry = top + (bottom - top) * (4 - rtick) / 4
                ctx.fillText(Math.round(graph.distanceAxisMax * rtick / 4),
                             right + 6, ry)
            }
            ctx.textAlign = "center"
            ctx.textBaseline = "top"
            var steps = Math.min(6, graph.frameAxisMax)
            for (var f = 0; f <= steps; f++) {
                var frame = Math.round(graph.frameAxisMax * f / steps)
                ctx.fillText(frame, plotX(frame), bottom + 6)
            }
            ctx.restore()
        }
    }

    // Canvas does not rebind, so every input that changes the drawing has to
    // ask for a repaint by hand.
    Connections {
        target: uiState
        function onDarkModeChanged() { plot.requestPaint() }
    }

    Connections {
        target: lm
        function onLanguageChanged() { plot.requestPaint() }
    }

    Component.onCompleted: plot.requestPaint()
}
