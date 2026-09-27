// Без консольного окна в релизной сборке (в debug консоль нужна для отладочного вывода).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    rupor_lib::run();
}
