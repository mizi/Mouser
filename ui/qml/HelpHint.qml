import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import "Theme.js" as Theme

// A small "?" that explains one control. A Popup reparented to the overlay,
// not a child Rectangle: the settings pages live inside a clipping ScrollView,
// which would cut a plain child off at the card edge.
FocusScope {
    id: hint

    property string text: ""
    property var theme
    property string fontFamily: "sans-serif"
    property int maxWidth: 260

    implicitWidth: 16
    implicitHeight: 16

    Accessible.role: Accessible.Button
    Accessible.name: "Help"
    Accessible.description: hint.text
    Accessible.onPressAction: bubble.opened ? bubble.close() : bubble.open()

    Keys.onReturnPressed: Accessible.onPressAction()
    Keys.onEnterPressed: Accessible.onPressAction()
    Keys.onSpacePressed: Accessible.onPressAction()

    Rectangle {
        id: badge
        anchors.fill: parent
        radius: width / 2
        color: mouse.containsMouse || hint.activeFocus
               ? (hint.theme ? hint.theme.bgCardHover : "transparent")
               : "transparent"
        border.width: 1
        border.color: hint.theme ? hint.theme.textDim : "#888888"

        Text {
            anchors.centerIn: parent
            text: "?"
            font {
                family: hint.fontFamily
                pixelSize: 10
                bold: true
            }
            color: hint.theme ? hint.theme.textSecondary : "#888888"
        }

        MouseArea {
            id: mouse
            anchors.fill: parent
            hoverEnabled: true
            // Same reason WheelSafeSlider sets it: a hover target sitting on
            // the page must never eat the wheel event that scrolls the page.
            scrollGestureEnabled: false
            cursorShape: Qt.PointingHandCursor
            onEntered: openTimer.restart()
            onExited: {
                openTimer.stop()
                if (!sticky)
                    closeTimer.restart()
            }
            onClicked: {
                sticky = !sticky
                if (sticky)
                    bubble.open()
                else
                    bubble.close()
            }
            property bool sticky: false
        }
    }

    Timer {
        id: openTimer
        interval: 350
        onTriggered: bubble.open()
    }

    Timer {
        id: closeTimer
        interval: 180
        onTriggered: if (!mouse.sticky) bubble.close()
    }

    Popup {
        id: bubble
        parent: Overlay.overlay
        x: hint.mapToItem(Overlay.overlay, 0, 0).x - width / 2 + hint.width / 2
        y: hint.mapToItem(Overlay.overlay, 0, 0).y + hint.height + 6
        width: Math.min(hint.maxWidth, bubbleText.implicitWidth + 24)
        height: bubbleText.implicitHeight + 20
        padding: 0
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

        background: Rectangle {
            radius: 8
            color: hint.theme ? hint.theme.tooltipBg : "#314055"
        }

        contentItem: Text {
            id: bubbleText
            anchors.centerIn: parent
            width: bubble.width - 24
            text: hint.text
            wrapMode: Text.WordWrap
            font {
                family: hint.fontFamily
                pixelSize: 11
            }
            color: hint.theme ? hint.theme.tooltipText : "#f8fafc"
        }
    }
}
