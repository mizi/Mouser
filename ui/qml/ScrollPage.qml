import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "Theme.js" as Theme

Item {
    id: scrollPage
    readonly property var theme: Theme.palette(uiState.darkMode)

    // Reactive shortcut — all s["key"] bindings update when lm.languageChanged fires
    property var s: lm.strings

    // Drawn from the slider handles rather than the config, so the graph tracks
    // the drag instead of waiting for the 400 ms commit.
    property var curveSamples: []
    property int previewBrake: backend.vscrollBrakePoint

    function previewCurve() {
        graphDebounce.restart()
    }

    function refreshCurve() {
        var duration = Math.round(durationSlider.value)
        var brake = Math.min(Math.round(brakeSlider.value), duration)
        scrollPage.previewBrake = brake
        scrollPage.curveSamples = backend.scrollCurveSamples(
            duration, brake,
            Math.round(vspeedSlider.value),
            Math.round(accelSlider.value),
            Math.round(smoothnessSlider.value))
    }

    function syncTuningSliders() {
        // _applyScrollTuning can write a value the user never touched -- the
        // brake point clamped by a lowered duration -- so the handles have to
        // be re-read, not only pushed.
        if (!durationSlider.pressed) {
            durationSlider.value = backend.vscrollDuration
            durationLabel.text = backend.vscrollDuration
        }
        if (!brakeSlider.pressed) {
            brakeSlider.value = backend.vscrollBrakePoint
            brakeLabel.text = backend.vscrollBrakePoint
        }
        if (!vspeedSlider.pressed) {
            vspeedSlider.value = backend.vscrollSpeed
            vspeedLabel.text = backend.vscrollSpeed
        }
        if (!accelSlider.pressed) {
            accelSlider.value = backend.vscrollAcceleration
            accelLabel.text = backend.vscrollAcceleration
        }
        if (!smoothnessSlider.pressed) {
            smoothnessSlider.value = backend.vscrollSmoothness
            smoothnessLabel.text = backend.vscrollSmoothness
        }
        if (!hspeedSlider.pressed) {
            hspeedSlider.value = backend.hscrollSpeed
            hspeedLabel.text = backend.hscrollSpeed
        }
        if (!modGainSlider.pressed) {
            modGainSlider.value = backend.modScrollGain
            modGainLabel.text = backend.modScrollGain.toFixed(1)
        }
        refreshCurve()
    }

    // Two timers on purpose. The graph redraws at about 16 fps while a slider
    // is dragged; the value is only committed, and the config only written,
    // once the drag settles.
    Timer {
        id: graphDebounce
        interval: 60
        onTriggered: scrollPage.refreshCurve()
    }

    Component.onCompleted: refreshCurve()

    ScrollView {
        id: pageScroll
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth

        Column {
            id: mainCol
            width: pageScroll.availableWidth
            spacing: 0

            Item {
                width: parent.width
                height: 96

                Column {
                    anchors {
                        left: parent.left
                        leftMargin: 36
                        verticalCenter: parent.verticalCenter
                    }
                    spacing: 4

                    Text {
                        text: s["scroll.title"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 24
                            bold: true
                        }
                        color: scrollPage.theme.textPrimary
                    }

                    Text {
                        text: s["scroll.subtitle"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 13
                        }
                        color: scrollPage.theme.textSecondary
                    }
                }
            }

            Rectangle {
                width: parent.width - 72
                height: 1
                color: scrollPage.theme.border
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Item { width: 1; height: 24 }

            // ── Physical Vertical Scroll ──────────────────────────

            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: physicalVContent.implicitHeight + 40
                radius: Theme.radius
                color: scrollPage.theme.bgCard
                border.width: 1
                border.color: scrollPage.theme.border

                Column {
                    id: physicalVContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 14

                    Text {
                        text: s["scroll.physical_v"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: scrollPage.theme.textPrimary
                    }

                    Text {
                        width: parent.width
                        text: s["scroll.physical_v_desc"]
                        wrapMode: Text.WordWrap
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: scrollPage.theme.textSecondary
                    }

                    ScrollCurveGraph {
                        id: curveGraph
                        width: parent.width
                        height: 180
                        samples: scrollPage.curveSamples
                        brakePoint: scrollPage.previewBrake
                        theme: scrollPage.theme
                        fontFamily: uiState.fontFamily
                        framesLabel: s["scroll.graph_frames"]
                        speedLabel: s["scroll.graph_speed"]
                        distanceLabel: s["scroll.graph_distance"]
                        boostedLabel: s["scroll.graph_boosted"]
                        brakeLabel: s["scroll.graph_brake"]
                    }

                    Row {
                        spacing: 16

                        Repeater {
                            model: [
                                { label: s["scroll.graph_speed"], color: scrollPage.theme.accent },
                                { label: s["scroll.graph_distance"], color: scrollPage.theme.warning },
                                { label: s["scroll.graph_boosted"], color: scrollPage.theme.textDim }
                            ]

                            Row {
                                spacing: 5

                                Rectangle {
                                    width: 10
                                    height: 3
                                    radius: 2
                                    anchors.verticalCenter: parent.verticalCenter
                                    color: modelData.color
                                }

                                Text {
                                    text: modelData.label
                                    font { family: uiState.fontFamily; pixelSize: 11 }
                                    color: scrollPage.theme.textDim
                                }
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: contentRowsmooth.implicitHeight + 20
                        radius: 10
                        color: scrollPage.theme.bgSubtle

                        RowLayout {
                            id: contentRowsmooth
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                            }
                            spacing: 12

                            Column {
                                Layout.fillWidth: true
                                spacing: 3

                                Row {
                                    spacing: 6

                                    Text {
                                        text: s["scroll.smooth_scroll"]
                                        font {
                                            family: uiState.fontFamily
                                            pixelSize: 13
                                        }
                                        color: scrollPage.theme.textPrimary
                                    }
                                    HelpHint {
                                        text: s["scroll.smooth_scroll_help"]
                                        theme: scrollPage.theme
                                        fontFamily: uiState.fontFamily
                                    }
                                }
                                Text {
                                    width: parent.width
                                    text: s["scroll.smooth_scroll_desc"]
                                    wrapMode: Text.WordWrap
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 11
                                    }
                                    color: scrollPage.theme.textDim
                                }
                            }

                            Switch {
                                id: smoothSwitch
                                checked: backend.vscrollSmooth
                                focusPolicy: Qt.StrongFocus
                                Material.accent: scrollPage.theme.accent
                                Accessible.name: s["scroll.smooth_scroll"]
                                onClicked: backend.setVScrollSmooth(checked)
                            }
                        }
                    }

                    Column {
                        width: parent.width
                        spacing: 8

                        Row {
                            spacing: 6

                            Text {
                                text: s["scroll.duration"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 13
                                    bold: true
                                }
                                color: scrollPage.theme.textPrimary
                            }
                        }

                        Text {
                            text: s["scroll.duration_desc"]
                            font {
                                family: uiState.fontFamily
                                pixelSize: 12
                            }
                            color: scrollPage.theme.textSecondary
                            wrapMode: Text.WordWrap
                            width: parent.width
                        }

                        RowLayout {
                            width: parent.width
                            spacing: 8

                            Text {
                                text: "2"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            WheelSafeSlider {
                                id: durationSlider
                                Layout.fillWidth: true
                                from: 2
                                to: 60
                                stepSize: 1
                                value: backend.vscrollDuration
                                accentColor: scrollPage.theme.accent
                                accentDimColor: scrollPage.theme.accentDim
                                trackColor: scrollPage.theme.border

                                onMoved: {
                                    durationLabel.text = Math.round(value)
                                    scrollPage.previewCurve()
                                    durationDebounce.restart()
                                }
                            }

                            Text {
                                text: "60"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            Rectangle {
                                Layout.preferredWidth: 72
                                Layout.preferredHeight: 36
                                radius: 10
                                color: scrollPage.theme.accentDim

                                Text {
                                    id: durationLabel
                                    anchors.centerIn: parent
                                    text: backend.vscrollDuration
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 14
                                        bold: true
                                    }
                                    color: scrollPage.theme.accent
                                }
                            }
                        }

                        Timer {
                            id: durationDebounce
                            interval: 400
                            onTriggered: backend.setVScrollDuration(Math.round(durationSlider.value))
                        }
                    }

                    Column {
                        width: parent.width
                        spacing: 8

                        Row {
                            spacing: 6

                            Text {
                                text: s["scroll.brake_point"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 13
                                    bold: true
                                }
                                color: scrollPage.theme.textPrimary
                            }
                        HelpHint {
                            text: s["scroll.brake_point_help"]
                            theme: scrollPage.theme
                            fontFamily: uiState.fontFamily
                        }
                        }

                        Text {
                            text: s["scroll.brake_point_desc"]
                            font {
                                family: uiState.fontFamily
                                pixelSize: 12
                            }
                            color: scrollPage.theme.textSecondary
                            wrapMode: Text.WordWrap
                            width: parent.width
                        }

                        RowLayout {
                            width: parent.width
                            spacing: 8

                            Text {
                                text: "1"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            WheelSafeSlider {
                                id: brakeSlider
                                Layout.fillWidth: true
                                from: 1
                                to: 12
                                stepSize: 1
                                value: backend.vscrollBrakePoint
                                accentColor: scrollPage.theme.accent
                                accentDimColor: scrollPage.theme.accentDim
                                trackColor: scrollPage.theme.border

                                onMoved: {
                                    brakeLabel.text = Math.round(value)
                                    scrollPage.previewCurve()
                                    brakeDebounce.restart()
                                }
                            }

                            Text {
                                text: "12"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            Rectangle {
                                Layout.preferredWidth: 72
                                Layout.preferredHeight: 36
                                radius: 10
                                color: scrollPage.theme.accentDim

                                Text {
                                    id: brakeLabel
                                    anchors.centerIn: parent
                                    text: backend.vscrollBrakePoint
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 14
                                        bold: true
                                    }
                                    color: scrollPage.theme.accent
                                }
                            }
                        }

                        Timer {
                            id: brakeDebounce
                            interval: 400
                            onTriggered: backend.setVScrollBrakePoint(Math.round(brakeSlider.value))
                        }
                    }

                    Column {
                        width: parent.width
                        spacing: 8

                        Row {
                            spacing: 6

                            Text {
                                text: s["scroll.scroll_speed"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 13
                                    bold: true
                                }
                                color: scrollPage.theme.textPrimary
                            }
                        }

                        Text {
                            text: s["scroll.scroll_speed_desc"]
                            font {
                                family: uiState.fontFamily
                                pixelSize: 12
                            }
                            color: scrollPage.theme.textSecondary
                            wrapMode: Text.WordWrap
                            width: parent.width
                        }

                        RowLayout {
                            width: parent.width
                            spacing: 8

                            Text {
                                text: "1"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            WheelSafeSlider {
                                id: vspeedSlider
                                Layout.fillWidth: true
                                from: 1
                                to: 50
                                stepSize: 1
                                value: backend.vscrollSpeed
                                accentColor: scrollPage.theme.accent
                                accentDimColor: scrollPage.theme.accentDim
                                trackColor: scrollPage.theme.border

                                onMoved: {
                                    vspeedLabel.text = Math.round(value)
                                    scrollPage.previewCurve()
                                    vspeedDebounce.restart()
                                }
                            }

                            Text {
                                text: "50"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            Rectangle {
                                Layout.preferredWidth: 72
                                Layout.preferredHeight: 36
                                radius: 10
                                color: scrollPage.theme.accentDim

                                Text {
                                    id: vspeedLabel
                                    anchors.centerIn: parent
                                    text: backend.vscrollSpeed
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 14
                                        bold: true
                                    }
                                    color: scrollPage.theme.accent
                                }
                            }
                        }

                        Timer {
                            id: vspeedDebounce
                            interval: 400
                            onTriggered: backend.setVScrollSpeed(Math.round(vspeedSlider.value))
                        }
                    }

                    Column {
                        width: parent.width
                        spacing: 8

                        Row {
                            spacing: 6

                            Text {
                                text: s["scroll.acceleration"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 13
                                    bold: true
                                }
                                color: scrollPage.theme.textPrimary
                            }
                        HelpHint {
                            text: s["scroll.acceleration_help"]
                            theme: scrollPage.theme
                            fontFamily: uiState.fontFamily
                        }
                        }

                        Text {
                            text: s["scroll.acceleration_desc"]
                            font {
                                family: uiState.fontFamily
                                pixelSize: 12
                            }
                            color: scrollPage.theme.textSecondary
                            wrapMode: Text.WordWrap
                            width: parent.width
                        }

                        RowLayout {
                            width: parent.width
                            spacing: 8

                            Text {
                                text: "0"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            WheelSafeSlider {
                                id: accelSlider
                                Layout.fillWidth: true
                                from: 0
                                to: 60
                                stepSize: 1
                                value: backend.vscrollAcceleration
                                accentColor: scrollPage.theme.accent
                                accentDimColor: scrollPage.theme.accentDim
                                trackColor: scrollPage.theme.border

                                onMoved: {
                                    accelLabel.text = Math.round(value)
                                    scrollPage.previewCurve()
                                    accelDebounce.restart()
                                }
                            }

                            Text {
                                text: "60"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            Rectangle {
                                Layout.preferredWidth: 72
                                Layout.preferredHeight: 36
                                radius: 10
                                color: scrollPage.theme.accentDim

                                Text {
                                    id: accelLabel
                                    anchors.centerIn: parent
                                    text: backend.vscrollAcceleration
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 14
                                        bold: true
                                    }
                                    color: scrollPage.theme.accent
                                }
                            }
                        }

                        Timer {
                            id: accelDebounce
                            interval: 400
                            onTriggered: backend.setVScrollAcceleration(Math.round(accelSlider.value))
                        }
                    }

                    Column {
                        width: parent.width
                        spacing: 8

                        Row {
                            spacing: 6

                            Text {
                                text: s["scroll.smoothness"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 13
                                    bold: true
                                }
                                color: scrollPage.theme.textPrimary
                            }
                        HelpHint {
                            text: s["scroll.smoothness_help"]
                            theme: scrollPage.theme
                            fontFamily: uiState.fontFamily
                        }
                        }

                        Text {
                            text: s["scroll.smoothness_desc"]
                            font {
                                family: uiState.fontFamily
                                pixelSize: 12
                            }
                            color: scrollPage.theme.textSecondary
                            wrapMode: Text.WordWrap
                            width: parent.width
                        }

                        RowLayout {
                            width: parent.width
                            spacing: 8

                            Text {
                                text: "0"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            WheelSafeSlider {
                                id: smoothnessSlider
                                Layout.fillWidth: true
                                from: 0
                                to: 5
                                stepSize: 1
                                value: backend.vscrollSmoothness
                                accentColor: scrollPage.theme.accent
                                accentDimColor: scrollPage.theme.accentDim
                                trackColor: scrollPage.theme.border

                                onMoved: {
                                    smoothnessLabel.text = Math.round(value)
                                    scrollPage.previewCurve()
                                    smoothnessDebounce.restart()
                                }
                            }

                            Text {
                                text: "5"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            Rectangle {
                                Layout.preferredWidth: 72
                                Layout.preferredHeight: 36
                                radius: 10
                                color: scrollPage.theme.accentDim

                                Text {
                                    id: smoothnessLabel
                                    anchors.centerIn: parent
                                    text: backend.vscrollSmoothness
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 14
                                        bold: true
                                    }
                                    color: scrollPage.theme.accent
                                }
                            }
                        }

                        Timer {
                            id: smoothnessDebounce
                            interval: 400
                            onTriggered: backend.setVScrollSmoothness(Math.round(smoothnessSlider.value))
                        }
                    }
                    Rectangle {
                        width: parent.width
                        height: 52
                        radius: 10
                        color: scrollPage.theme.bgSubtle

                        RowLayout {
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                            }

                            Text {
                                text: s["scroll.invert_vertical"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 13
                                }
                                color: scrollPage.theme.textPrimary
                                Layout.fillWidth: true
                            }

                            Switch {
                                id: vscrollSwitch
                                checked: backend.invertVScroll
                                focusPolicy: Qt.StrongFocus
                                Material.accent: scrollPage.theme.accent
                                Accessible.name: s["scroll.invert_vertical"]
                                onClicked: backend.setInvertVScroll(checked)
                            }
                        }
                    }


                }
            }

            Item { width: 1; height: 16 }

            // ── Scroll Wheel Mode (device firmware) ───────────────
            Item { width: 1; height: 16; visible: backend.smartShiftSupported && backend.deviceHasSmartShift }

            // ── Scroll Wheel Mode ─────────────────────────────────
            Rectangle {
                visible: backend.smartShiftSupported && backend.deviceHasSmartShift
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: smartShiftContent.implicitHeight + 40
                radius: Theme.radius
                color: scrollPage.theme.bgCard
                border.width: 1
                border.color: scrollPage.theme.border

                Column {
                    id: smartShiftContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 16

                    // ── SmartShift header row with toggle ───────────────
                    RowLayout {
                        width: parent.width

                        Column {
                            spacing: 4
                            Layout.fillWidth: true

                            Text {
                                text: s["scroll.smart_shift"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 16
                                    bold: true
                                }
                                color: scrollPage.theme.textPrimary
                            }

                            Text {
                                text: s["scroll.smart_shift_desc"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 12
                                }
                                color: scrollPage.theme.textSecondary
                                wrapMode: Text.WordWrap
                                width: parent.width
                            }
                        }

                        Switch {
                            id: smartShiftToggle
                            checked: backend.smartShiftEnabled
                            focusPolicy: Qt.StrongFocus
                            Material.accent: scrollPage.theme.accent
                            Accessible.name: s["scroll.smart_shift"]
                            onClicked: backend.setSmartShiftEnabled(checked)
                        }
                    }

                    // ── Sensitivity slider (visible when SmartShift ON) ─
                    Column {
                        visible: backend.smartShiftEnabled
                        width: parent.width
                        spacing: 8

                        Text {
                            text: s["scroll.sensitivity_value"]
                            font {
                                family: uiState.fontFamily
                                pixelSize: 11
                                bold: true
                                letterSpacing: 0.8
                            }
                            color: scrollPage.theme.textDim
                        }

                        RowLayout {
                            width: parent.width
                            spacing: 8

                            Text {
                                text: "1"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            WheelSafeSlider {
                                id: smartShiftSlider
                                Layout.fillWidth: true
                                from: 1
                                to: 50
                                stepSize: 1
                                value: backend.smartShiftThreshold
                                accentColor: scrollPage.theme.accent
                                accentDimColor: scrollPage.theme.accentDim
                                trackColor: scrollPage.theme.border

                                onMoved: {
                                    smartShiftLabel.text = Math.round(value * 2) + "%"
                                    smartShiftDebounce.restart()
                                }
                            }

                            Text {
                                text: "50"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            Rectangle {
                                Layout.preferredWidth: 72
                                Layout.preferredHeight: 36
                                radius: 10
                                color: scrollPage.theme.accentDim

                                Text {
                                    id: smartShiftLabel
                                    anchors.centerIn: parent
                                    text: Math.round(backend.smartShiftThreshold * 2) + "%"
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 14
                                        bold: true
                                    }
                                    color: scrollPage.theme.accent
                                }
                            }
                        }

                        Timer {
                            id: smartShiftDebounce
                            interval: 400
                            onTriggered: backend.setSmartShiftThreshold(Math.round(smartShiftSlider.value))
                        }
                    }

                    // ── Scroll Mode (hidden when SmartShift ON) ─────────
                    Column {
                        visible: !backend.smartShiftEnabled
                        width: parent.width
                        spacing: 8

                        Text {
                            text: s["scroll.scroll_mode_section"]
                            font {
                                family: uiState.fontFamily
                                pixelSize: 11
                                bold: true
                                letterSpacing: 0.8
                            }
                            color: scrollPage.theme.textDim
                        }

                        Row {
                            width: parent.width
                            spacing: 10

                            Repeater {
                                model: [
                                    { value: "ratchet",  labelKey: "scroll.ratchet"  },
                                    { value: "freespin", labelKey: "scroll.freespin" }
                                ]

                                delegate: Rectangle {
                                    required property var modelData
                                    width: Math.max(96, ssText.implicitWidth + 28)
                                    height: 38
                                    radius: 10
                                    color: backend.smartShiftMode === modelData.value
                                           ? scrollPage.theme.accentDim
                                           : scrollPage.theme.bgSubtle
                                    border.width: backend.smartShiftMode === modelData.value ? 2 : 1
                                    border.color: backend.smartShiftMode === modelData.value
                                                  ? scrollPage.theme.accent
                                                  : scrollPage.theme.border

                                    Accessible.role: Accessible.Button
                                    Accessible.name: ssText.text
                                    Accessible.checkable: true
                                    Accessible.checked: backend.smartShiftMode === modelData.value
                                    Accessible.onPressAction: backend.setSmartShift(modelData.value)

                                    Text {
                                        id: ssText
                                        anchors.centerIn: parent
                                        text: s[modelData.labelKey] || modelData.labelKey
                                        font {
                                            family: uiState.fontFamily
                                            pixelSize: 12
                                            bold: backend.smartShiftMode === modelData.value
                                        }
                                        color: backend.smartShiftMode === modelData.value
                                               ? scrollPage.theme.accent
                                               : scrollPage.theme.textPrimary
                                    }

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: backend.setSmartShift(modelData.value)
                                    }
                                }
                            }
                        }
                    }

                    // ── Scroll Force slider (enhanced 0x2111 only; hidden in freespin) ──
                    Column {
                        visible: backend.smartShiftForceSupported
                                 && (backend.smartShiftEnabled || backend.smartShiftMode === "ratchet")
                        width: parent.width
                        spacing: 8

                        Text {
                            text: s["scroll.scroll_force_value"] || "FORCE"
                            font {
                                family: uiState.fontFamily
                                pixelSize: 11
                                bold: true
                                letterSpacing: 0.8
                            }
                            color: scrollPage.theme.textDim
                        }

                        Text {
                            text: s["scroll.scroll_force_desc"]
                            font {
                                family: uiState.fontFamily
                                pixelSize: 12
                            }
                            color: scrollPage.theme.textSecondary
                            wrapMode: Text.WordWrap
                            width: parent.width
                        }

                        RowLayout {
                            width: parent.width
                            spacing: 8

                            Text {
                                text: "1"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            WheelSafeSlider {
                                id: scrollForceSlider
                                Layout.fillWidth: true
                                from: 1
                                to: 100
                                stepSize: 1
                                value: backend.scrollForce
                                accentColor: scrollPage.theme.accent
                                accentDimColor: scrollPage.theme.accentDim
                                trackColor: scrollPage.theme.border

                                onMoved: {
                                    scrollForceLabel.text = Math.round(value) + "%"
                                    scrollForceDebounce.restart()
                                }
                            }

                            Text {
                                text: "100"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            Rectangle {
                                Layout.preferredWidth: 72
                                Layout.preferredHeight: 36
                                radius: 10
                                color: scrollPage.theme.accentDim

                                Text {
                                    id: scrollForceLabel
                                    anchors.centerIn: parent
                                    text: backend.scrollForce + "%"
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 14
                                        bold: true
                                    }
                                    color: scrollPage.theme.accent
                                }
                            }
                        }

                        Timer {
                            id: scrollForceDebounce
                            interval: 400
                            onTriggered: backend.setScrollForce(Math.round(scrollForceSlider.value))
                        }
                    }
                }
            }

            Item { width: 1; height: 16 }

            // ── Physical Horizontal Scroll ────────────────────────

            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: physicalHContent.implicitHeight + 40
                radius: Theme.radius
                color: scrollPage.theme.bgCard
                border.width: 1
                border.color: scrollPage.theme.border

                Column {
                    id: physicalHContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 14

                    Text {
                        text: s["scroll.physical_h"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: scrollPage.theme.textPrimary
                    }

                    Text {
                        width: parent.width
                        text: s["scroll.physical_h_desc"]
                        wrapMode: Text.WordWrap
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: scrollPage.theme.textSecondary
                    }

                    Column {
                        width: parent.width
                        spacing: 8

                        Row {
                            spacing: 6

                            Text {
                                text: s["scroll.hscroll_speed"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 13
                                    bold: true
                                }
                                color: scrollPage.theme.textPrimary
                            }
                        }

                        Text {
                            text: s["scroll.hscroll_speed_desc"]
                            font {
                                family: uiState.fontFamily
                                pixelSize: 12
                            }
                            color: scrollPage.theme.textSecondary
                            wrapMode: Text.WordWrap
                            width: parent.width
                        }

                        RowLayout {
                            width: parent.width
                            spacing: 8

                            Text {
                                text: "1"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            WheelSafeSlider {
                                id: hspeedSlider
                                Layout.fillWidth: true
                                from: 1
                                to: 50
                                stepSize: 1
                                value: backend.hscrollSpeed
                                accentColor: scrollPage.theme.accent
                                accentDimColor: scrollPage.theme.accentDim
                                trackColor: scrollPage.theme.border

                                onMoved: {
                                    hspeedLabel.text = Math.round(value)
                                    scrollPage.previewCurve()
                                    hspeedDebounce.restart()
                                }
                            }

                            Text {
                                text: "50"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            Rectangle {
                                Layout.preferredWidth: 72
                                Layout.preferredHeight: 36
                                radius: 10
                                color: scrollPage.theme.accentDim

                                Text {
                                    id: hspeedLabel
                                    anchors.centerIn: parent
                                    text: backend.hscrollSpeed
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 14
                                        bold: true
                                    }
                                    color: scrollPage.theme.accent
                                }
                            }
                        }

                        Timer {
                            id: hspeedDebounce
                            interval: 400
                            onTriggered: backend.setHScrollSpeed(Math.round(hspeedSlider.value))
                        }
                    }
                    Rectangle {
                        width: parent.width
                        height: 52
                        radius: 10
                        color: scrollPage.theme.bgSubtle

                        RowLayout {
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                            }

                            Text {
                                text: s["scroll.invert_horizontal"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 13
                                }
                                color: scrollPage.theme.textPrimary
                                Layout.fillWidth: true
                            }

                            Switch {
                                id: hscrollSwitch
                                checked: backend.invertHScroll
                                focusPolicy: Qt.StrongFocus
                                Material.accent: scrollPage.theme.accent
                                Accessible.name: s["scroll.invert_horizontal"]
                                onClicked: backend.setInvertHScroll(checked)
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 62
                        radius: 10
                        color: scrollPage.theme.bgSubtle
                        visible: backend.isMacOS

                        RowLayout {
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                            }
                            spacing: 12

                            Column {
                                Layout.fillWidth: true
                                spacing: 3

                                Text {
                                    text: s["scroll.ignore_trackpad"]
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 13
                                    }
                                    color: scrollPage.theme.textPrimary
                                }

                                Text {
                                    width: parent.width
                                    text: s["scroll.ignore_trackpad_desc"]
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 11
                                    }
                                    color: scrollPage.theme.textSecondary
                                    wrapMode: Text.WordWrap
                                }
                            }

                            Switch {
                                id: ignoreTrackpadSwitch
                                checked: backend.ignoreTrackpad
                                Material.accent: scrollPage.theme.accent
                                Accessible.name: s["scroll.ignore_trackpad"]
                                onToggled: backend.setIgnoreTrackpad(checked)
                            }
                        }
                    }

                }
            }

            Item { width: 1; height: 16 }

            // ── Modified Vertical Scroll ──────────────────────────

            Rectangle {
                width: parent.width - 72
                anchors.horizontalCenter: parent.horizontalCenter
                height: modifiedVContent.implicitHeight + 40
                radius: Theme.radius
                color: scrollPage.theme.bgCard
                border.width: 1
                border.color: scrollPage.theme.border

                Column {
                    id: modifiedVContent
                    anchors {
                        left: parent.left
                        right: parent.right
                        top: parent.top
                        margins: 20
                    }
                    spacing: 14

                    Text {
                        text: s["scroll.modified_v"]
                        font {
                            family: uiState.fontFamily
                            pixelSize: 16
                            bold: true
                        }
                        color: scrollPage.theme.textPrimary
                    }

                    Text {
                        width: parent.width
                        text: s["scroll.modified_v_desc"]
                        wrapMode: Text.WordWrap
                        font {
                            family: uiState.fontFamily
                            pixelSize: 12
                        }
                        color: scrollPage.theme.textSecondary
                    }

                    Rectangle {
                        width: parent.width
                        height: contentRowmodShift.implicitHeight + 20
                        radius: 10
                        color: scrollPage.theme.bgSubtle

                        RowLayout {
                            id: contentRowmodShift
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                            }
                            spacing: 12

                            Column {
                                Layout.fillWidth: true
                                spacing: 3

                                Row {
                                    spacing: 6

                                    Text {
                                        text: s["scroll.mod_shift_hscroll"]
                                        font {
                                            family: uiState.fontFamily
                                            pixelSize: 13
                                        }
                                        color: scrollPage.theme.textPrimary
                                    }
                                }
                                Text {
                                    width: parent.width
                                    text: s["scroll.mod_shift_hscroll_desc"]
                                    wrapMode: Text.WordWrap
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 11
                                    }
                                    color: scrollPage.theme.textDim
                                }
                            }

                            Switch {
                                id: modShiftSwitch
                                checked: backend.modScrollShiftHScroll
                                focusPolicy: Qt.StrongFocus
                                Material.accent: scrollPage.theme.accent
                                Accessible.name: s["scroll.mod_shift_hscroll"]
                                onClicked: backend.setModScrollShiftHScroll(checked)
                            }
                        }
                    }

                    // ── Per-app Shift+wheel ───────────────────────────
                    // Some apps bind Shift+wheel themselves (MS Project expands
                    // and collapses summary tasks with it), so each app
                    // profile can follow the switch above or override it.
                    Column {
                        width: parent.width
                        spacing: 8
                        leftPadding: 16

                        Text {
                            text: s["scroll.mod_shift_per_app"]
                            font {
                                family: uiState.fontFamily
                                pixelSize: 13
                                bold: true
                            }
                            color: scrollPage.theme.textPrimary
                        }

                        Text {
                            width: parent.width - parent.leftPadding
                            text: backend.profileShiftHScroll.length
                                  ? s["scroll.mod_shift_per_app_desc"]
                                  : s["scroll.mod_shift_per_app_empty"]
                            wrapMode: Text.WordWrap
                            font {
                                family: uiState.fontFamily
                                pixelSize: 11
                            }
                            color: scrollPage.theme.textDim
                        }

                        Repeater {
                            model: backend.profileShiftHScroll

                            delegate: Rectangle {
                                id: perAppRow
                                required property var modelData
                                width: parent.width - parent.leftPadding
                                height: 50
                                radius: 10
                                color: scrollPage.theme.bgSubtle

                                RowLayout {
                                    anchors {
                                        fill: parent
                                        leftMargin: 16
                                        rightMargin: 10
                                    }
                                    spacing: 8

                                    Text {
                                        text: perAppRow.modelData.label
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                        font {
                                            family: uiState.fontFamily
                                            pixelSize: 13
                                        }
                                        color: scrollPage.theme.textPrimary
                                    }

                                    Repeater {
                                        model: [
                                            { value: "inherit", labelKey: "scroll.per_app_follow" },
                                            { value: "on",      labelKey: "scroll.per_app_on" },
                                            { value: "off",     labelKey: "scroll.per_app_off" }
                                        ]

                                        delegate: Rectangle {
                                            required property var modelData
                                            readonly property bool selected:
                                                perAppRow.modelData.mode === modelData.value
                                            Layout.preferredWidth: Math.max(64, chipText.implicitWidth + 24)
                                            Layout.preferredHeight: 32
                                            radius: 8
                                            color: selected ? scrollPage.theme.accentDim
                                                            : scrollPage.theme.bgCard
                                            border.width: selected ? 2 : 1
                                            border.color: selected ? scrollPage.theme.accent
                                                                   : scrollPage.theme.border

                                            Accessible.role: Accessible.Button
                                            Accessible.name: perAppRow.modelData.label + ": " + chipText.text
                                            Accessible.checkable: true
                                            Accessible.checked: selected
                                            Accessible.onPressAction: backend.setProfileShiftHScroll(
                                                perAppRow.modelData.name, modelData.value)

                                            Text {
                                                id: chipText
                                                anchors.centerIn: parent
                                                text: s[modelData.labelKey]
                                                font {
                                                    family: uiState.fontFamily
                                                    pixelSize: 12
                                                    bold: parent.selected
                                                }
                                                color: parent.selected ? scrollPage.theme.accent
                                                                       : scrollPage.theme.textPrimary
                                            }

                                            MouseArea {
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: backend.setProfileShiftHScroll(
                                                    perAppRow.modelData.name, modelData.value)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: contentRowmodCtrl.implicitHeight + 20
                        radius: 10
                        color: scrollPage.theme.bgSubtle

                        RowLayout {
                            id: contentRowmodCtrl
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                            }
                            spacing: 12

                            Column {
                                Layout.fillWidth: true
                                spacing: 3

                                Row {
                                    spacing: 6

                                    Text {
                                        text: s["scroll.mod_ctrl_zoom"]
                                        font {
                                            family: uiState.fontFamily
                                            pixelSize: 13
                                        }
                                        color: scrollPage.theme.textPrimary
                                    }
                                }
                                Text {
                                    width: parent.width
                                    text: s["scroll.mod_ctrl_zoom_desc"]
                                    wrapMode: Text.WordWrap
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 11
                                    }
                                    color: scrollPage.theme.textDim
                                }
                            }

                            Switch {
                                id: modCtrlSwitch
                                checked: backend.modScrollCtrlZoom
                                focusPolicy: Qt.StrongFocus
                                Material.accent: scrollPage.theme.accent
                                Accessible.name: s["scroll.mod_ctrl_zoom"]
                                onClicked: backend.setModScrollCtrlZoom(checked)
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: contentRowmodFast.implicitHeight + 20
                        radius: 10
                        color: scrollPage.theme.bgSubtle

                        RowLayout {
                            id: contentRowmodFast
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                            }
                            spacing: 12

                            Column {
                                Layout.fillWidth: true
                                spacing: 3

                                Row {
                                    spacing: 6

                                    Text {
                                        text: backend.isMacOS ? s["scroll.mod_cmd_fast"] : s["scroll.mod_super_fast"]
                                        font {
                                            family: uiState.fontFamily
                                            pixelSize: 13
                                        }
                                        color: scrollPage.theme.textPrimary
                                    }
                                }
                                Text {
                                    width: parent.width
                                    text: backend.isMacOS ? s["scroll.mod_cmd_fast_desc"] : s["scroll.mod_super_fast_desc"]
                                    wrapMode: Text.WordWrap
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 11
                                    }
                                    color: scrollPage.theme.textDim
                                }
                            }

                            Switch {
                                id: modFastSwitch
                                checked: backend.modScrollCmdFast
                                focusPolicy: Qt.StrongFocus
                                Material.accent: scrollPage.theme.accent
                                Accessible.name: backend.isMacOS ? s["scroll.mod_cmd_fast"] : s["scroll.mod_super_fast"]
                                onClicked: backend.setModScrollCmdFast(checked)
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: contentRowmodInvertH.implicitHeight + 20
                        radius: 10
                        color: scrollPage.theme.bgSubtle

                        RowLayout {
                            id: contentRowmodInvertH
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                            }
                            spacing: 12

                            Column {
                                Layout.fillWidth: true
                                spacing: 3

                                Row {
                                    spacing: 6

                                    Text {
                                        text: s["scroll.mod_invert_hscroll"]
                                        font {
                                            family: uiState.fontFamily
                                            pixelSize: 13
                                        }
                                        color: scrollPage.theme.textPrimary
                                    }
                                }
                                Text {
                                    width: parent.width
                                    text: s["scroll.mod_invert_hscroll_desc"]
                                    wrapMode: Text.WordWrap
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 11
                                    }
                                    color: scrollPage.theme.textDim
                                }
                            }

                            Switch {
                                id: modInvertHSwitch
                                checked: backend.modScrollInvertHScroll
                                focusPolicy: Qt.StrongFocus
                                Material.accent: scrollPage.theme.accent
                                Accessible.name: s["scroll.mod_invert_hscroll"]
                                onClicked: backend.setModScrollInvertHScroll(checked)
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: contentRowmodInvertZoom.implicitHeight + 20
                        radius: 10
                        color: scrollPage.theme.bgSubtle

                        RowLayout {
                            id: contentRowmodInvertZoom
                            anchors {
                                fill: parent
                                leftMargin: 16
                                rightMargin: 16
                            }
                            spacing: 12

                            Column {
                                Layout.fillWidth: true
                                spacing: 3

                                Row {
                                    spacing: 6

                                    Text {
                                        text: s["scroll.mod_invert_zoom"]
                                        font {
                                            family: uiState.fontFamily
                                            pixelSize: 13
                                        }
                                        color: scrollPage.theme.textPrimary
                                    }
                                }
                                Text {
                                    width: parent.width
                                    text: s["scroll.mod_invert_zoom_desc"]
                                    wrapMode: Text.WordWrap
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 11
                                    }
                                    color: scrollPage.theme.textDim
                                }
                            }

                            Switch {
                                id: modInvertZoomSwitch
                                checked: backend.modScrollInvertZoom
                                focusPolicy: Qt.StrongFocus
                                Material.accent: scrollPage.theme.accent
                                Accessible.name: s["scroll.mod_invert_zoom"]
                                onClicked: backend.setModScrollInvertZoom(checked)
                            }
                        }
                    }

                    Column {
                        width: parent.width
                        spacing: 8

                        Row {
                            spacing: 6

                            Text {
                                text: s["scroll.mod_gain"]
                                font {
                                    family: uiState.fontFamily
                                    pixelSize: 13
                                    bold: true
                                }
                                color: scrollPage.theme.textPrimary
                            }
                        HelpHint {
                            text: s["scroll.mod_gain_help"]
                            theme: scrollPage.theme
                            fontFamily: uiState.fontFamily
                        }
                        }

                        Text {
                            text: s["scroll.mod_gain_desc"]
                            font {
                                family: uiState.fontFamily
                                pixelSize: 12
                            }
                            color: scrollPage.theme.textSecondary
                            wrapMode: Text.WordWrap
                            width: parent.width
                        }

                        RowLayout {
                            width: parent.width
                            spacing: 8

                            Text {
                                text: "0.1"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            WheelSafeSlider {
                                id: modGainSlider
                                Layout.fillWidth: true
                                from: 0.1
                                to: 10.0
                                stepSize: 0.1
                                value: backend.modScrollGain
                                accentColor: scrollPage.theme.accent
                                accentDimColor: scrollPage.theme.accentDim
                                trackColor: scrollPage.theme.border

                                onMoved: {
                                    modGainLabel.text = value.toFixed(1)
                                    scrollPage.previewCurve()
                                    modGainDebounce.restart()
                                }
                            }

                            Text {
                                text: "10.0"
                                font { family: uiState.fontFamily; pixelSize: 11 }
                                color: scrollPage.theme.textDim
                            }

                            Rectangle {
                                Layout.preferredWidth: 72
                                Layout.preferredHeight: 36
                                radius: 10
                                color: scrollPage.theme.accentDim

                                Text {
                                    id: modGainLabel
                                    anchors.centerIn: parent
                                    text: backend.modScrollGain.toFixed(1)
                                    font {
                                        family: uiState.fontFamily
                                        pixelSize: 14
                                        bold: true
                                    }
                                    color: scrollPage.theme.accent
                                }
                            }
                        }

                        Timer {
                            id: modGainDebounce
                            interval: 400
                            onTriggered: backend.setModScrollGain(modGainSlider.value)
                        }
                    }

                }
            }

            Item { width: 1; height: 24 }
        }
    }

    Connections {
        target: backend
        function onScrollSettingsChanged() {
            scrollPage.syncTuningSliders()
        }
        function onSettingsChanged() {
            vscrollSwitch.checked = backend.invertVScroll
            hscrollSwitch.checked = backend.invertHScroll
            ignoreTrackpadSwitch.checked = backend.ignoreTrackpad
        }
        function onSmartShiftChanged() {
            if (!scrollForceSlider.pressed) {
                scrollForceSlider.value = backend.scrollForce
                scrollForceLabel.text = backend.scrollForce + "%"
            }
            if (!smartShiftSlider.pressed) {
                smartShiftSlider.value = backend.smartShiftThreshold
                smartShiftLabel.text = Math.round(backend.smartShiftThreshold * 2) + "%"
            }
        }
    }
}
