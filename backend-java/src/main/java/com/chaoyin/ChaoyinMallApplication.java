package com.chaoyin;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
@MapperScan("com.chaoyin.mapper")
public class ChaoyinMallApplication {

    public static void main(String[] args) {
        SpringApplication.run(ChaoyinMallApplication.class, args);
    }
}
